"""Execute the installed 120-byte payload through the mocked Thumb executor."""
from pathlib import Path
import unittest
try:
    from thumb_executor import Thumb, DISABLED
except ModuleNotFoundError as error:
    if error.name != 'capstone':
        raise
    raise unittest.SkipTest('Capstone is required for the optional Thumb instruction tests')


class MinimalStubTests(unittest.TestCase):
    def cpu(self):
        return Thumb((Path(__file__).resolve().parents[1] / 'custom-touch-250-min.bin').read_bytes())

    def test_size(self):
        self.assertEqual((Path(__file__).resolve().parents[1] / 'custom-touch-250-min.bin').stat().st_size, 120)

    def test_both_routes_toggle(self):
        cpu = self.cpu()
        cpu.invoke(0x43, 0x0825796f)
        cpu.invoke(8, 0x0825609d)
        cpu.invoke(4, 0x08257957)
        self.assertEqual(cpu.setter_calls, [1, 0])

    def test_held_repeats_toggle_once_until_release(self):
        cpu = self.cpu()
        for _ in range(3):
            cpu.invoke(0x43, 0x0825796f)
        self.assertEqual(cpu.setter_calls, [1])
        cpu.invoke(8, 0x0825609d)
        for _ in range(3):
            cpu.invoke(0x43, 0x0825796f)
        self.assertEqual(cpu.setter_calls, [1, 0])
        cpu.invoke(0x80, 0x08257987)
        cpu.invoke(0x43, 0x0825796f)
        self.assertEqual(cpu.setter_calls, [1, 0, 1])

    def test_boolean_inversion_all_byte_values(self):
        for value in range(256):
            cpu = self.cpu()
            cpu.mem[DISABLED] = value
            cpu.invoke(0x43, 0x0825796f)
            self.assertEqual(cpu.setter_calls, [int(value == 0)])

    def test_release_and_preludes_consumed(self):
        cpu = self.cpu()
        for site in [0x0825608f, 0x0825609d, 0x082560af, 0x082560bd, 0x08257987]:
            for event in [4, 0x43, 8, 0x80, 0x10]:
                cpu.invoke(event, site)
        self.assertEqual(cpu.setter_calls, [])
        self.assertEqual(cpu.forwarded, [])

    def test_other_sites_and_wrong_events_forward(self):
        cpu = self.cpu()
        # Include nearby origins to catch an overly broad compressed filter.
        sites = [0x0825608f, 0x0825609d, 0x082560af, 0x082560bd]
        for site in range(0x08256080, 0x082560c4):
            if site not in sites:
                cpu.invoke(0x43, site)
        for event, site in [(4, 0x0825796f), (0x43, 0x08257957),
                            (0x800, 0x082582c1), (0x43, 0x08257515)]:
            cpu.invoke(event, site)
        self.assertEqual(len(cpu.forwarded), 68)
        self.assertEqual(cpu.setter_calls, [])


if __name__ == '__main__':
    unittest.main()
