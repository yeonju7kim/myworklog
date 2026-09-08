from __future__ import annotations

import subprocess
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MyWorkLog"


def startup_command() -> str:
    """Return the command Windows should run after the user signs in."""
    if getattr(sys, "frozen", False):
        arguments = [str(Path(sys.executable).resolve()), "--background"]
    else:
        project_root = Path(__file__).resolve().parent.parent
        python_executable = Path(sys.executable).resolve()
        pythonw_executable = python_executable.with_name("pythonw.exe")
        if not pythonw_executable.exists():
            pythonw_executable = python_executable
        arguments = [
            str(pythonw_executable),
            str(project_root / "main.py"),
            "--background",
        ]
    return subprocess.list2cmdline(arguments)


def is_autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _value_type = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return str(value) == startup_command()


def set_autostart_enabled(enabled: bool) -> None:
    """Add or remove MyWorkLog from the current user's startup programs."""
    if sys.platform != "win32":
        raise OSError("자동 실행은 Windows에서만 사용할 수 있습니다.")

    import winreg

    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass

