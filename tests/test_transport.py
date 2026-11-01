"""Fast path omits only ATT acknowledgment, without changing RACE exchange."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import struct
import custom_touch_250 as poc


class FastTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_connection_and_pipeline_are_defaults(self):
        client = poc.Client('usb:0')
        self.assertIsInstance(client.transport, poc.FastGATTTransport)
        self.assertEqual(client.transport.address, poc.DEFAULT_ADDRESS)
        self.assertEqual(client.window, 4)

    async def test_att_write_without_response(self):
        transport = poc.FastGATTTransport('usb:0', 'C0:2E:A7:E9:FF:00', [], False)
        transport.client = AsyncMock()
        transport.tx_char_handle = object()
        await transport.send(b'packet')
        transport.client.write_value.assert_awaited_once_with(
            transport.tx_char_handle, b'packet', with_response=False)

    async def test_known_address_skips_name_request(self):
        client = poc.Client('usb:0', address='C0:2E:A7:E9:FF:00')
        self.assertIsInstance(client.transport, poc.FastGATTTransport)
        self.assertEqual(client.transport.address, 'C0:2E:A7:E9:FF:00')
        self.assertEqual(client.transport.name, 'LE_WH-1000XM4')
        self.assertEqual(client.exchanges, 0)

    async def test_cached_setup_registers_notification_and_cccd(self):
        transport = poc.FastGATTTransport('usb:0', None, [], False)
        transport.connection = object()
        gatt = SimpleNamespace(notification_subscribers={}, write_value=AsyncMock(),
                               request_mtu=AsyncMock(return_value=242),
                               read_value=AsyncMock(return_value=b'\x01\x00'))
        recv = lambda data: None
        with patch.object(poc, 'Peer', return_value=SimpleNamespace(gatt_client=gatt)):
            await transport.setup_gatt(recv)
        self.assertEqual(transport.tx_char_handle, 0x53)
        self.assertIn(transport._recv_internal, gatt.notification_subscribers[0x55])
        gatt.write_value.assert_awaited_once_with(0x56, b'\x01\x00', with_response=True)
        gatt.request_mtu.assert_awaited_once_with(256)
        gatt.read_value.assert_awaited_once_with(0x56)
        self.assertEqual(transport.negotiated_mtu, 242)

    async def test_read_window_correlates_fragmented_out_of_order_replies(self):
        client = poc.Client('usb:0')
        addresses = [0x0823c6ac, 0x0823c6b0, 0x0823c6b4]
        expected = {address: i+10 for i, address in enumerate(addresses)}
        sent = []
        async def send(packet):
            sent.append(struct.unpack_from('<I', packet, 8)[0])
            if len(sent) == 3:
                frames = b''.join(poc.RacePacket(
                    poc.RaceHeader(5, poc.RaceType.RESPONSE, 0x1680),
                    struct.pack('<B H I I', 0, 0, address, expected[address])
                ).pack() for address in reversed(addresses))
                for part in (frames[:3], frames[3:24], frames[24:]):
                    client.queue.put_nowait(part)
        client.transport.send = send
        self.assertEqual(await client.read_window(addresses), expected)
        self.assertEqual(sent, addresses)
        self.assertEqual(client.exchanges, 3)

    async def test_read_window_rejects_unknown_address(self):
        client = poc.Client('usb:0')
        async def send(packet):
            client.queue.put_nowait(poc.RacePacket(
                poc.RaceHeader(5, poc.RaceType.RESPONSE, 0x1680),
                struct.pack('<B H I I', 0, 0, 0x0823c6b0, 0)
            ).pack())
        client.transport.send = send
        with self.assertRaisesRegex(RuntimeError, 'address or status'):
            await client.read_window([0x0823c6ac])

    async def test_write_window_verifies_real_addresses(self):
        for corrupt in [False, True]:
            client = poc.Client('usb:0')
            words = [(0x100667c0+i*4, i+10) for i in range(4)]
            memory = {}
            async def send(packet):
                command = struct.unpack_from('<H', packet, 4)[0]
                address = struct.unpack_from('<I', packet, 8)[0]
                if command == 0x1681:
                    memory[address] = struct.unpack_from('<I', packet, 12)[0]
                    payload = b'\0'
                else:
                    value = memory[address] ^ int(corrupt)
                    payload = struct.pack('<B H I I', 0, 0, address, value)
                client.queue.put_nowait(poc.RacePacket(
                    poc.RaceHeader(5, poc.RaceType.RESPONSE, command), payload).pack())
            client.transport.send = send
            if corrupt:
                with self.assertRaisesRegex(RuntimeError, 'readback mismatch'):
                    await client.write_window(words)
            else:
                await client.write_window(words)
                self.assertEqual(memory, dict(words))
                self.assertEqual(client.exchanges, 8)

