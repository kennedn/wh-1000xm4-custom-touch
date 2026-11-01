"""Malformed and changing allocator metadata must not drive arbitrary reads."""
import unittest
import custom_touch_250 as poc


class HeapFake:
    def __init__(self):
        self.words = dict(zip(poc.HEAP_GLOBALS.values(),
                              [0x100, poc.HEAP_END, poc.HEAP_START,
                               poc.HEAP_START, 0x80000000, 0x80]))
        self.words.update({poc.HEAP_START: poc.HEAP_END,
                           poc.HEAP_START + 4: 0x100,
                           poc.HEAP_END: 0, poc.HEAP_END + 4: 0})
        self.reads = []

    async def read32(self, address):
        self.reads.append(address)
        return self.words[address]


class HeapTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_candidate(self):
        result = await poc.heap_snapshot(HeapFake(), 196)
        self.assertIsNone(result['error'])
        self.assertEqual(result['required_total'], 216)
        self.assertEqual(result['blocks'][0]['payload'], poc.HEAP_START + 16)
        self.assertTrue(result['blocks'][0]['fits'])

    async def test_metadata_reads_stay_serial_with_upload_window(self):
        client = HeapFake()
        client.window = 4
        async def forbidden(*args):
            raise AssertionError('Changing metadata must not use read windows')
        client.read_window = forbidden
        result = await poc.heap_snapshot(client, 120)
        self.assertIsNone(result['error'])

    async def test_bad_first_pointer_not_followed(self):
        client = HeapFake()
        client.words[poc.HEAP_GLOBALS['first']] = 0xDEADBEE0
        result = await poc.heap_snapshot(client, 196)
        self.assertIsNotNone(result['error'])
        self.assertNotIn(0xDEADBEE0, client.reads)

    async def test_cycle_and_allocated_size_rejected(self):
        for field, value in [(poc.HEAP_START, poc.HEAP_START),
                             (poc.HEAP_START + 4, 0x80000100)]:
            client = HeapFake()
            client.words[field] = value
            result = await poc.heap_snapshot(client, 196)
            self.assertIsNotNone(result['error'])
            self.assertEqual(result['blocks'], [])

    async def test_activity_is_reported(self):
        client = HeapFake()
        original = client.read32
        async def changing(address):
            value = await original(address)
            if address == poc.HEAP_END + 4:
                client.words[poc.HEAP_GLOBALS['free_bytes']] -= 8
            return value
        client.read32 = changing
        result = await poc.heap_snapshot(client, 196)
        self.assertTrue(result['globals_changed'])

    async def test_bad_size_preserves_serial_reread_evidence(self):
        client = HeapFake()
        client.words[poc.HEAP_START+4] = 0xa2900000
        result = await poc.heap_snapshot(client, 120)
        evidence = result['invalid_header']
        self.assertEqual(evidence['size'], 0xa2900000)
        self.assertEqual(evidence['reread_size'], 0xa2900000)
        self.assertEqual(evidence['address'], poc.HEAP_START)
        self.assertEqual(result['blocks'], [])


if __name__ == '__main__':
    unittest.main()
