"""The installer CLI has one always-quick execution path."""
import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch
import custom_touch_250 as poc


class DummyClient:
    def __init__(self):
        self.exchanges = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class CliTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_subcommand_or_fast_flag_needed(self):
        args = poc.make_parser().parse_args([])
        with patch.object(poc, 'Client', return_value=DummyClient()) as factory, \
             patch.object(poc, 'install_minimal', new_callable=AsyncMock) as install:
            await poc.main(args)
        factory.assert_called_once_with('usb:0', address=None)
        self.assertIsNone(install.call_args.args[1])
        self.assertEqual(install.call_args.kwargs, dict(dynamic=False, skip_verify=False))

    async def test_dynamic_is_forwarded(self):
        args = poc.make_parser().parse_args(['--dynamic'])
        with patch.object(poc, 'Client', return_value=DummyClient()), \
             patch.object(poc, 'install_minimal', new_callable=AsyncMock) as install:
            await poc.main(args)
        self.assertTrue(install.call_args.kwargs['dynamic'])
        self.assertIsNone(install.call_args.args[1])

    async def test_skip_verify_is_forwarded(self):
        args = poc.make_parser().parse_args(['--skip-verify'])
        with patch.object(poc, 'Client', return_value=DummyClient()), \
             patch.object(poc, 'install_minimal', new_callable=AsyncMock) as install:
            await poc.main(args)
        self.assertTrue(install.call_args.kwargs['skip_verify'])

    async def test_explicit_connection_and_scratch(self):
        args = poc.make_parser().parse_args([
            '--controller', 'usb:1', '--address', 'C0:2E:A7:E9:FF:00',
            '--scratch', '0x10066830'])
        with patch.object(poc, 'Client', return_value=DummyClient()) as factory, \
             patch.object(poc, 'install_minimal', new_callable=AsyncMock) as install:
            await poc.main(args)
        factory.assert_called_once_with('usb:1', address='C0:2E:A7:E9:FF:00')
        self.assertEqual(install.call_args.args[1], poc.DEFAULT_SCRATCH)

    def test_legacy_commands_are_not_in_quick_installer(self):
        for arguments in [['--fast'], ['install-minimal'], ['inspect'], ['--state', 'old.json']]:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    poc.make_parser().parse_args(arguments)
