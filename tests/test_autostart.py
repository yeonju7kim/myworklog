from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from myworklog import autostart


class AutostartTests(unittest.TestCase):
    def test_development_command_uses_pythonw_and_background_flag(self) -> None:
        command = autostart.startup_command()

        self.assertIn("pythonw.exe", command.lower())
        self.assertIn(str(Path("main.py")), command)
        self.assertTrue(command.endswith("--background"))

    @unittest.skipUnless(sys.platform == "win32", "Windows registry behavior")
    def test_enabled_requires_current_command(self) -> None:
        fake_winreg = MagicMock()
        fake_winreg.HKEY_CURRENT_USER = object()
        fake_winreg.QueryValueEx.return_value = (autostart.startup_command(), 1)

        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            self.assertTrue(autostart.is_autostart_enabled())

        fake_winreg.QueryValueEx.return_value = ("old command", 1)
        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            self.assertFalse(autostart.is_autostart_enabled())

    @unittest.skipUnless(sys.platform == "win32", "Windows registry behavior")
    def test_set_enabled_writes_current_user_run_value(self) -> None:
        fake_winreg = MagicMock()
        fake_winreg.HKEY_CURRENT_USER = object()
        fake_winreg.REG_SZ = 1

        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            autostart.set_autostart_enabled(True)

        fake_winreg.SetValueEx.assert_called_once_with(
            fake_winreg.CreateKey.return_value.__enter__.return_value,
            autostart.VALUE_NAME,
            0,
            fake_winreg.REG_SZ,
            autostart.startup_command(),
        )


if __name__ == "__main__":
    unittest.main()
