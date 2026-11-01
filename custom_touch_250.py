"""
Install a temporary XM4 2.5.0 CUSTOM long-press touch toggle.
Installed under fixed unreserved RAM by default (DEFAULT_SCRATCH), --dynamic selects from a live free list.
A local race-toolkit checkout and custom-touch-250-min.bin are required.
"""
import argparse
import asyncio
import hashlib
from pathlib import Path
import struct
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "race-toolkit"))
from librace.transport import GATTBumbleTransport
from librace.packets import RaceHeader, RacePacket, ReadAddress
from librace.constants import RaceType
from bumble.device import Peer

DEFAULT_ADDRESS = "C0:2E:A7:E9:FF:00"

ROOT = 0x10068B10
TABLE = 0x10003D38
ORIGINAL = 0x08263BB5
HEAP_START = 0x100068C0
HEAP_END = 0x100668A8
MINIMAL_SHA = "ec7550567bc9cb36bc44e6b956a6fe21e0ceb6fc6106f0cd9a2fa75e8ed7b64a"
MINIMAL_SIZE = 120
DEFAULT_SCRATCH = 0x10066830
QUICK_CODE_WORDS = {0x081DCCB4: 0x4B12B57F, 0x0823C6AC: 0x4B0CB537}
HEAP_GLOBALS = dict(free_bytes=0x100068A0, end=0x100068A4,
                    first=0x100068A8, arena=0x100068B8,
                    allocation_mask=0x100668BC, minimum_free=0x100668C0)


async def read_words(client, addresses):
    window = getattr(client, 'window', 1)
    values = {}
    for offset in range(0, len(addresses), window):
        chunk = addresses[offset:offset+window]
        if window == 1:
            values[chunk[0]] = await client.read32(chunk[0])
        else:
            values.update(await client.read_window(chunk))
    return values


async def heap_snapshot(client, stub_size, max_nodes=128):
    """Bounded metadata reads only; a snapshot is not an atomic reservation."""
    async def globals_now():
        return {name: await client.read32(address) for name, address in HEAP_GLOBALS.items()}
    result = dict(globals=await globals_now(), blocks=[], error=None)
    g = result["globals"]
    required = (stub_size + 16 + 7) & ~7
    result["required_total"] = required
    try:
        if g["end"] != HEAP_END or g["allocation_mask"] != 0x80000000:
            raise ValueError("Unexpected heap end or allocation mask")
        if g["arena"] not in (0x100068BC, HEAP_START):
            raise ValueError("Unexpected initial arena pointer")
        if not 0 <= g["minimum_free"] <= g["free_bytes"] <= HEAP_END - HEAP_START:
            raise ValueError("Invalid free-byte counters")
        address = g["first"]
        previous_end = HEAP_START
        for _ in range(max_nodes):
            if address == HEAP_END:
                if await client.read32(address) or await client.read32(address+4):
                    raise ValueError("Invalid end sentinel")
                break
            if address & 7 or not HEAP_START <= address < HEAP_END or address < previous_end:
                raise ValueError(f"Invalid/overlapping free header 0x{address:08x}")
            following = await client.read32(address)
            size = await client.read32(address+4)
            if size & 0x80000007 or size < 16 or address + size > HEAP_END:
                result['invalid_header'] = dict(address=address, next=following, size=size,
                    reread_next=await client.read32(address), reread_size=await client.read32(address+4))
                raise ValueError(f"Invalid free size 0x{size:x} at 0x{address:08x}")
            if following & 7 or not address + size <= following <= HEAP_END:
                raise ValueError(f"Invalid next pointer 0x{following:08x}")
            result["blocks"].append(dict(header=address, next=following, total=size,
                                          payload=address + 16, available=size - 16,
                                          fits=size >= required))
            previous_end = address + size
            address = following
        else:
            raise ValueError(f"Stopped at {max_nodes}-node limit")
        if sum(block["total"] for block in result["blocks"]) != g["free_bytes"]:
            raise ValueError("Free-list total differs from free-byte counter (possible activity)")
    except ValueError as exc:
        result["error"] = str(exc)
    result["globals_after"] = await globals_now()
    result["globals_changed"] = result["globals_after"] != g
    return result


def select_scratch(snapshot, size, requested=None):
    """Choose from this snapshot only; historical availability is not ownership."""
    if snapshot['error'] or snapshot['globals_changed']:
        raise ValueError("Cannot select memory from an invalid/changing snapshot")
    candidates = []
    for block in snapshot['blocks']:
        start, end = block['payload'], block['header'] + block['total']
        address = requested if requested is not None else (end-size) & ~7
        if address % 4 == 0 and start <= address and address+size <= end:
            candidates.append((address, block))
    if not candidates:
        raise RuntimeError("Requested range is not inside a validated free payload" if requested is not None
                           else "No live free payload fits the stub")
    return max(candidates, key=lambda candidate: candidate[0])


async def find_live_scratch(client, size, requested=None):
    for attempt in range(1, 4):
        snapshot = await heap_snapshot(client, size)
        error = snapshot['error'] or ('globals changed' if snapshot['globals_changed'] else None)
        if error is None:
            address, block = select_scratch(snapshot, size, requested)
            # Recheck just the selected header immediately before returning.
            following = await client.read32(block['header'])
            total = await client.read32(block['header']+4)
            if (following, total) == (block['next'], block['total']):
                return address
            error = 'selected free header changed'
        if attempt < 3:
            print(f"Heap check retry ({attempt}/3): {error}")
    raise RuntimeError(f"Heap did not validate in 3 attempts; no upload: {error}")


class FastGATTTransport(GATTBumbleTransport):
    async def send(self, data):
        # Sony TX advertises WRITE_WITHOUT_RESPONSE. RACE replies still ACK
        # every command; only the additional ATT write response is omitted.
        await self.client.write_value(self.tx_char_handle, data, with_response=False)

    async def setup_gatt(self, recv_fn):
        # XM4 2.5.0 handles already observed live. Keep MTU negotiation from
        # the proven setup: firmware's BLE reply path uses a cached MTU limit.
        self.client = Peer(self.connection).gatt_client
        self.negotiated_mtu = await self.client.request_mtu(256)
        self.tx_char_handle = 0x0053
        self.recv_fn = recv_fn
        self.client.notification_subscribers.setdefault(0x0055, set()).add(self._recv_internal)
        await self.client.write_value(0x0056, b"\x01\x00", with_response=True)
        if await self.client.read_value(0x0056) != b"\x01\x00":
            raise RuntimeError("Sony RX notifications are not enabled")


class Client:
    def __init__(self, controller, address=None):
        self.transport = FastGATTTransport(controller, address or DEFAULT_ADDRESS, ["WH-1000XM4"], False)
        self.transport.name = "LE_WH-1000XM4"
        self.queue = asyncio.Queue()
        self.exchanges = 0
        self.window = 4

    async def __aenter__(self):
        try:
            await asyncio.wait_for(self.transport.setup(lambda data: self.queue.put_nowait(bytes(data))), 60)
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *args):
        await asyncio.wait_for(self.transport.close(), 5)

    def link_parameters(self):
        parameters = self.transport.connection.parameters
        return (f"interval={parameters.connection_interval * 1.25:g}ms, "
                f"latency={parameters.peripheral_latency}, "
                f"timeout={parameters.supervision_timeout * 10:g}ms")

    async def exchange(self, packet, command):
        self.exchanges += 1
        while not self.queue.empty():
            self.queue.get_nowait()
        await asyncio.wait_for(self.transport.send(packet.pack()), 8)
        data = b""
        async def wait():
            nonlocal data
            while True:
                data += await self.queue.get()
                if len(data) >= 6:
                    header = RaceHeader.unpack(data[:6])
                    if len(data) >= header.length + 4:
                        if header.id != command or header.type != RaceType.RESPONSE:
                            raise RuntimeError("Unexpected RACE reply")
                        return data[6:header.length + 4]
        return await asyncio.wait_for(wait(), 8)

    async def read32(self, address):
        if address & 3:
            raise ValueError("Unaligned read")
        reply = await self.exchange(ReadAddress(address), 0x1680)
        if len(reply) != 11 or reply[0] != 0 or struct.unpack_from("<HI", reply, 1) != (0, address):
            raise RuntimeError(f"Invalid read at 0x{address:08x}")
        return struct.unpack_from("<I", reply, 7)[0]

    async def read_window(self, addresses):
        """Read-only experimental pipeline. Never run alongside exchange()."""
        if len(addresses) != len(set(addresses)) or any(a & 3 for a in addresses):
            raise ValueError("Pipeline requires unique aligned addresses")
        limit = 8
        if not 1 <= len(addresses) <= limit:
            raise ValueError(f"Read window must contain 1..{limit} addresses")
        if not self.queue.empty():
            raise RuntimeError("Pending data before read window")
        await self.send_window([ReadAddress(address).pack() for address in addresses])
        pending = set(addresses)
        values = {}
        buffer = b""
        async def receive():
            nonlocal buffer
            while pending:
                buffer += await self.queue.get()
                while len(buffer) >= 6:
                    header = RaceHeader.unpack(buffer[:6])
                    if header.head != 5 or header.id != 0x1680 or header.type != RaceType.RESPONSE or header.length != 13:
                        raise RuntimeError("Unexpected pipelined read frame")
                    length = header.length + 4
                    if len(buffer) < length:
                        break
                    reply, buffer = buffer[6:length], buffer[length:]
                    status, module, address, value = struct.unpack('<B H I I', reply)
                    if status or module or address not in pending:
                        raise RuntimeError("Unexpected/duplicate pipelined read address or status")
                    pending.remove(address)
                    values[address] = value
            if buffer:
                raise RuntimeError("Extra data after read window")
            return values
        return await asyncio.wait_for(receive(), 8)

    async def write32(self, address, value, verify=True):
        if address & 3 or not 0x10000000 <= address <= 0x1007FFFC:
            raise ValueError("Only aligned SRAM writes are permitted")
        packet = RacePacket(RaceHeader(5, RaceType.CMD_EXPECTS_RESPONSE, 0x1681), struct.pack("<HII", 0, address, value))
        if await self.exchange(packet, 0x1681) != b"\0":
            raise RuntimeError(f"Write failed at 0x{address:08x}")
        if verify and await self.read32(address) != value:
            raise RuntimeError(f"Write verification failed at 0x{address:08x}")

    async def send_window(self, packets):
        self.exchanges += len(packets)
        for packet in packets:
            await asyncio.wait_for(self.transport.send(packet), 8)

    async def write_window(self, words, verify=True):
        """Bounded scratch writes; always ACK each request, optionally read back."""
        limit = 4
        if not 1 <= len(words) <= limit or len({a for a, _ in words}) != len(words):
            raise ValueError(f"Write window requires 1..{limit} unique addresses")
        if any(a & 3 or not 0x10000000 <= a <= 0x1007FFFC for a, _ in words):
            raise ValueError("Only aligned SRAM writes are permitted")
        if not self.queue.empty():
            raise RuntimeError("Pending data before write window")
        packets = []
        for address, value in words:
            packet = RacePacket(RaceHeader(5, RaceType.CMD_EXPECTS_RESPONSE, 0x1681),
                                struct.pack('<HII', 0, address, value))
            packets.append(packet.pack())
        await self.send_window(packets)
        async def acknowledgments():
            buffer = b''
            received = 0
            while received < len(words):
                buffer += await self.queue.get()
                while len(buffer) >= 6:
                    header = RaceHeader.unpack(buffer[:6])
                    if (header.head, header.type, header.id, header.length) != (5, RaceType.RESPONSE, 0x1681, 3):
                        raise RuntimeError("Unexpected pipelined write frame")
                    if len(buffer) < 7:
                        break
                    if buffer[6] != 0 or received >= len(words):
                        raise RuntimeError("Pipelined write failed or extra ACK")
                    buffer = buffer[7:]
                    received += 1
            if buffer:
                raise RuntimeError("Extra data after write window")
        await asyncio.wait_for(acknowledgments(), 8)
        expected = dict(words)
        if verify and await self.read_window(list(expected)) != expected:
            raise RuntimeError("Pipelined write readback mismatch")

    async def read(self, address, size):
        addresses = list(range(address, address+size, 4))
        words = await read_words(self, addresses)
        return b''.join(struct.pack('<I', words[a]) for a in addresses)

    async def write(self, address, blob, verify=True):
        if len(blob) % 4:
            raise ValueError("Unaligned blob")
        window = getattr(self, 'window', 1)
        for start in range(0, len(blob), window*4):
            words = [(address+offset, struct.unpack_from('<I', blob, offset)[0])
                     for offset in range(start, min(start+window*4, len(blob)), 4)]
            if window == 1:
                if verify:
                    await self.write32(*words[0])
                else:
                    await self.write32(*words[0], verify=False)
            else:
                await self.write_window(words, verify=verify)


async def install_minimal(client, scratch=None, timings=None, dynamic=False, skip_verify=False):
    """Install the tested immutable binary; accepted unreserved, fleeting PoC."""
    phase_start = perf_counter()
    def stamp(name):
        nonlocal phase_start
        now = perf_counter()
        if timings is not None:
            timings[name] = now - phase_start
        phase_start = now
    blob = (HERE / "custom-touch-250-min.bin").read_bytes()
    if len(blob) != MINIMAL_SIZE or hashlib.sha256(blob).hexdigest() != MINIMAL_SHA:
        raise RuntimeError("Unexpected minimal binary; no writes performed")
    if scratch is not None and scratch & 3:
        raise ValueError("Scratch must be word-aligned")
    if not dynamic:
        scratch = DEFAULT_SCRATCH if scratch is None else scratch
        if not HEAP_START+16 <= scratch or scratch+len(blob) > HEAP_END:
            raise ValueError("Fixed scratch must fit inside the heap payload arena")
    stamp("local checks")
    expected = {ROOT: TABLE, TABLE: ORIGINAL, 0x100068A4: HEAP_END,
                HEAP_END: 0, HEAP_END+4: 0}
    expected.update(QUICK_CODE_WORDS)
    # Serial reads deliberately isolate this preflight from the unproven
    # behavior of pipelined reads of changing allocator metadata.
    for address, value in expected.items():
        actual = await client.read32(address)
        if actual != value:
            detail = f"expected 0x{value:08x}, found 0x{actual:08x}"
            if address == TABLE:
                detail += "; callback is not stock, possibly an existing hook. Reboot the headset before reinstalling"
            raise RuntimeError(f"Preflight mismatch at 0x{address:08x}: {detail}; no writes performed")
    stamp("preflight")
    if dynamic:
        scratch = await find_live_scratch(client, len(blob), scratch)
        stamp("live memory selection")
        print(f"Selected 0x{scratch:08x} from current free payload; storage remains unreserved.")
    else:
        print(f"Using fixed 0x{scratch:08x}; current free-list membership is not checked.")
    try:
        if skip_verify:
            await client.write(scratch, blob, verify=False)
        else:
            await client.write(scratch, blob)
        stamp("upload (ACK only)" if skip_verify else "upload + readback")
        # Publish only after every stub write is acknowledged, and by default
        # read back too. Attachment itself always retains readback verification.
        await client.write32(TABLE, scratch | 1)
        stamp("attach callback")
    except BaseException:
        # A failed publish may have taken effect. Detach if possible; never
        # replay scratch bytes into potentially changed heap ownership.
        try:
            await client.write32(TABLE, ORIGINAL)
        except Exception as error:
            print(f"Could not confirm callback detachment: {error}; reboot the headset.")
        raise
    print(f"Installed {len(blob)}-byte always-on hook at 0x{scratch:08x}.")
    if skip_verify:
        print("Stub readback skipped; all write ACKs and callback readback checked.")
    print("CUSTOM long-press toggles touch controls. Reboot clears the hook.")


async def main(args):
    timings = {}
    started = perf_counter()
    client = Client(args.controller, address=args.address)
    try:
        async with client:
            timings["connect/setup"] = perf_counter() - started
            if args.timings:
                print("BLE:", client.link_parameters())
                print(f"MTU={client.transport.negotiated_mtu}, RX CCCD verified=0100")
            await install_minimal(client, args.scratch, timings,
                                  dynamic=args.dynamic, skip_verify=args.skip_verify)
            close_start = perf_counter()
        timings["disconnect"] = perf_counter() - close_start
    finally:
        if args.timings:
            for name, duration in timings.items():
                print(f"{name}: {duration:.3f}s")
            print(f"total (after imports): {perf_counter()-started:.3f}s; RACE exchanges: {client.exchanges}")


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", default="usb:0")
    parser.add_argument("--address", help="Override the known BLE address")
    parser.add_argument("--timings", action="store_true", help="Print phase durations and RACE exchange count")
    parser.add_argument("--skip-verify", action="store_true", help="Skip stub readback; retain every write ACK and callback-pointer readback")
    parser.add_argument("--dynamic", action="store_true", help="Select/check placement from the live free list instead of the fixed default")
    parser.add_argument("--scratch", type=lambda x: int(x, 0),
                        help="Address override (default: 0x10066830); --dynamic requires a current free payload")
    return parser


if __name__ == "__main__":
    asyncio.run(main(make_parser().parse_args()))
