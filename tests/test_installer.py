"""Minimal upload ordering, live-region gating and failure detachment."""
from pathlib import Path
import tempfile
import struct
import unittest
from unittest.mock import patch
import custom_touch_250 as poc


class Fake(poc.Client):
    """Only the live words needed by quick preflight; no stock image fixture."""
    def __init__(self):
        self.memory = {}
        self.writes = []
        self.fail_at = None
        for address, value in {poc.ROOT: poc.TABLE, poc.TABLE: poc.ORIGINAL,
                               **poc.QUICK_CODE_WORDS}.items():
            self.word(address, value)

    def word(self, address, value):
        for index, byte in enumerate(struct.pack('<I', value)):
            self.memory[address+index] = byte

    async def read32(self, address):
        return int.from_bytes(bytes(self.memory.get(address+i, 0) for i in range(4)), 'little')

    async def write32(self, address, value):
        if self.fail_at == address:
            self.fail_at = None
            raise RuntimeError('simulated write failure')
        self.writes.append((address, value))
        self.word(address, value)



class MinimalHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'state.json'
        self.client = Fake()
        self.scratch = 0x100667c0
        header = 0x1001b0c0
        values = dict(free_bytes=poc.HEAP_END-header, end=poc.HEAP_END,
                      first=header, arena=poc.HEAP_START,
                      allocation_mask=0x80000000, minimum_free=0x100)
        for name, value in values.items():
            self.client.word(poc.HEAP_GLOBALS[name], value)
        self.client.word(header, poc.HEAP_END)
        self.client.word(header+4, poc.HEAP_END-header)
        # Use actual binaries, keeping any unexpected file writes isolated.
        self.real_here = poc.HERE
        poc.HERE = Path(self.directory.name)
        for name in ['custom-touch-250-min.bin']:
            (poc.HERE / name).symlink_to(self.real_here / name)

    async def asyncTearDown(self):
        poc.HERE = self.real_here
        self.directory.cleanup()

    async def test_publish_last(self):
        await poc.install_minimal(self.client, self.scratch, dynamic=True)
        self.assertEqual(len(self.client.writes), poc.MINIMAL_SIZE // 4 + 1)
        self.assertEqual(self.client.writes[-1], (poc.TABLE, self.scratch | 1))
        self.assertFalse(self.path.exists())

    async def test_default_fixed_address_does_not_scan_heap(self):
        with patch.object(poc, 'heap_snapshot', side_effect=AssertionError('No fixed-path heap walk')):
            await poc.install_minimal(self.client)
        self.assertEqual(self.client.writes[0][0], 0x10066830)
        self.assertEqual(self.client.writes[-1], (poc.TABLE, 0x10066831))
        self.assertFalse(self.path.exists())

    async def test_fast_install_without_local_firmware_image(self):
        self.assertFalse((poc.HERE / 'main_cpu_2.5.0.bin').exists())
        for dynamic in [False, True]:
            self.client.word(poc.TABLE, poc.ORIGINAL)
            self.client.writes.clear()
            await poc.install_minimal(self.client, dynamic=dynamic)
            self.assertEqual(self.client.writes[-1][0], poc.TABLE)

    async def test_embedded_instruction_mismatch_rejects_before_writes(self):
        address = next(iter(poc.QUICK_CODE_WORDS))
        self.client.word(address, poc.QUICK_CODE_WORDS[address] ^ 1)
        with self.assertRaisesRegex(RuntimeError, 'Preflight mismatch'):
            await poc.install_minimal(self.client)
        self.assertEqual(self.client.writes, [])

    async def test_attached_callback_error_reports_pointer_and_reboot(self):
        self.client.word(poc.TABLE, poc.DEFAULT_SCRATCH | 1)
        with self.assertRaisesRegex(RuntimeError, 'expected 0x08263bb5, found 0x10066831.*Reboot'):
            await poc.install_minimal(self.client)
        self.assertEqual(self.client.writes, [])

    async def test_skip_verify_retains_acks_and_attachment_readback(self):
        for window in [1, 4]:
            for failed_ack in [False, True]:
                self.client.word(poc.TABLE, poc.ORIGINAL)
                self.client.writes.clear()
                wire = poc.Client('usb:0')
                wire.window = window
                reads = []
                async def send(packet):
                    command = struct.unpack_from('<H', packet, 4)[0]
                    address = struct.unpack_from('<I', packet, 8)[0]
                    if command == 0x1681:
                        if failed_ack and address == poc.DEFAULT_SCRATCH + 8:
                            payload = b'\x03'
                        else:
                            await self.client.write32(address, struct.unpack_from('<I', packet, 12)[0])
                            payload = b'\0'
                    else:
                        reads.append(address)
                        payload = struct.pack('<B H I I', 0, 0, address, await self.client.read32(address))
                    wire.queue.put_nowait(poc.RacePacket(
                        poc.RaceHeader(5, poc.RaceType.RESPONSE, command), payload).pack())
                wire.transport.send = send
                if failed_ack:
                    with self.assertRaisesRegex(RuntimeError, 'write failed|Write failed'):
                        await poc.install_minimal(wire, skip_verify=True)
                    self.assertNotIn((poc.TABLE, poc.DEFAULT_SCRATCH | 1), self.client.writes)
                    self.assertEqual(self.client.writes[-1], (poc.TABLE, poc.ORIGINAL))
                else:
                    await poc.install_minimal(wire, skip_verify=True)
                    self.assertEqual(wire.exchanges, 39)
                    self.assertEqual(self.client.writes[-1], (poc.TABLE, poc.DEFAULT_SCRATCH | 1))
                self.assertFalse(any(poc.DEFAULT_SCRATCH <= a < poc.DEFAULT_SCRATCH+poc.MINIMAL_SIZE for a in reads))
                self.assertEqual(reads[-1], poc.TABLE)

    async def test_fixed_outside_heap_rejected_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'inside the heap'):
            await poc.install_minimal(self.client, poc.TABLE)
        self.assertEqual(self.client.writes, [])

    async def test_no_scratch_backup_or_persistent_files(self):
        original_read = self.client.read32
        async def read32(address):
            if self.scratch <= address < self.scratch + poc.MINIMAL_SIZE:
                self.assertTrue(self.client.writes, 'Scratch read before upload is an unnecessary backup')
            return await original_read(address)
        self.client.read32 = read32
        timings = {}
        before = set(poc.HERE.iterdir())
        await poc.install_minimal(self.client, self.scratch, timings, dynamic=True)
        self.assertEqual(set(poc.HERE.iterdir()), before)
        self.assertNotIn('backup', timings)

    async def test_failed_upload_detaches_without_restoring_heap(self):
        self.client.fail_at = self.scratch + 8
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            await poc.install_minimal(self.client, self.scratch, dynamic=True)
        self.assertEqual(self.client.writes[-1], (poc.TABLE, poc.ORIGINAL))
        self.assertEqual(len(self.client.writes), 3)
        self.assertFalse(self.path.exists())

    async def test_outside_free_payload_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'not inside'):
            await poc.install_minimal(self.client, poc.TABLE, dynamic=True)
        self.assertEqual(self.client.writes, [])

    async def test_nonstock_callback_rejected_and_old_backups_untouched(self):
        self.client.word(poc.TABLE, self.scratch | 1)
        with self.assertRaisesRegex(RuntimeError, 'Preflight mismatch'):
            await poc.install_minimal(self.client, self.scratch, dynamic=True)
        self.client.word(poc.TABLE, poc.ORIGINAL)
        self.path.write_text('retain me')
        await poc.install_minimal(self.client, self.scratch, dynamic=True)
        self.assertEqual(self.path.read_text(), 'retain me')
        self.assertEqual(self.client.writes[-1], (poc.TABLE, self.scratch | 1))

    async def test_pipelined_install_publish_last_and_failure_detaches(self):
        for fail in [False, True]:
            wire = poc.Client('usb:0')
            wire.window = 4
            self.client.word(poc.TABLE, poc.ORIGINAL)
            self.client.writes.clear()
            if fail:
                self.client.fail_at = self.scratch + 8
            async def send(packet):
                command = struct.unpack_from('<H', packet, 4)[0]
                address = struct.unpack_from('<I', packet, 8)[0]
                if command == 0x1681:
                    await self.client.write32(address, struct.unpack_from('<I', packet, 12)[0])
                    payload = b'\0'
                else:
                    payload = struct.pack('<B H I I', 0, 0, address, await self.client.read32(address))
                wire.queue.put_nowait(poc.RacePacket(
                    poc.RaceHeader(5, poc.RaceType.RESPONSE, command), payload).pack())
            wire.transport.send = send
            if fail:
                with self.assertRaisesRegex(RuntimeError, 'simulated'):
                    await poc.install_minimal(wire, self.scratch, dynamic=True)
                self.assertNotIn((poc.TABLE, self.scratch | 1), self.client.writes)
                self.assertEqual(self.client.writes[-1], (poc.TABLE, poc.ORIGINAL))
            else:
                await poc.install_minimal(wire, self.scratch, dynamic=True)
                self.assertEqual(self.client.writes[-1], (poc.TABLE, self.scratch | 1))

    async def test_heap_race_retries_before_any_upload(self):
        valid = await poc.heap_snapshot(self.client, poc.MINIMAL_SIZE)
        attempts = 0
        async def racing_heap(*args):
            nonlocal attempts
            attempts += 1
            self.assertEqual(self.client.writes, [])
            if attempts == 1:
                return dict(error='Invalid free size 0x80000020', globals_changed=True)
            return valid
        with patch.object(poc, 'heap_snapshot', side_effect=racing_heap):
            await poc.install_minimal(self.client, self.scratch, dynamic=True)
        self.assertEqual(attempts, 2)
        self.assertEqual(self.client.writes[-1], (poc.TABLE, self.scratch | 1))

    async def test_heap_race_retry_limit_never_uploads(self):
        async def racing_heap(*args):
            return dict(error='Invalid free size 0x80000020', globals_changed=True)
        with patch.object(poc, 'heap_snapshot', side_effect=racing_heap) as snapshots:
            with self.assertRaisesRegex(RuntimeError, '3 attempts'):
                await poc.install_minimal(self.client, self.scratch, dynamic=True)
        self.assertEqual(snapshots.call_count, 3)
        self.assertEqual(self.client.writes, [])
        self.assertFalse(self.path.exists())

    async def test_fast_preflight_still_checks_live_heap(self):
        with patch.object(poc, 'heap_snapshot', wraps=poc.heap_snapshot) as snapshots:
            await poc.install_minimal(self.client, self.scratch, dynamic=True)
        snapshots.assert_awaited_once()
        self.assertEqual(self.client.writes[-1], (poc.TABLE, self.scratch | 1))
        self.assertFalse(self.path.exists())

    async def test_quick_checks_callback_and_sentinel_before_writes(self):
        for address in [poc.TABLE, poc.HEAP_END]:
            old = await self.client.read32(address)
            self.client.word(address, old ^ 1)
            with self.assertRaisesRegex(RuntimeError, 'Preflight mismatch'):
                await poc.install_minimal(self.client, self.scratch, dynamic=True)
            self.client.word(address, old)
        self.assertEqual(self.client.writes, [])
        self.assertFalse(self.path.exists())

    async def test_fast_rejects_range_outside_live_free_payload(self):
        with self.assertRaisesRegex(RuntimeError, 'not inside'):
            await poc.install_minimal(self.client, poc.TABLE, dynamic=True)
        self.assertEqual(self.client.writes, [])

    async def test_auto_selection_follows_current_block_end(self):
        header = 0x1001b0c0
        for size in [0x400, 0x800]:
            self.client.word(poc.TABLE, poc.ORIGINAL)
            self.client.word(header+4, size)
            self.client.word(poc.HEAP_GLOBALS['free_bytes'], size)
            self.client.writes.clear()
            await poc.install_minimal(self.client, dynamic=True)
            expected = (header+size-poc.MINIMAL_SIZE) & ~7
            self.assertEqual(self.client.writes[0][0], expected)
            self.assertEqual(self.client.writes[-1], (poc.TABLE, expected | 1))

    async def test_selected_header_change_stops_upload(self):
        valid = await poc.heap_snapshot(self.client, poc.MINIMAL_SIZE)
        self.client.word(valid['blocks'][0]['header']+4, 0x80000020)
        with patch.object(poc, 'heap_snapshot', return_value=valid):
            with self.assertRaisesRegex(RuntimeError, 'selected free header changed'):
                await poc.install_minimal(self.client, dynamic=True)
        self.assertEqual(self.client.writes, [])


if __name__ == '__main__':
    unittest.main()
