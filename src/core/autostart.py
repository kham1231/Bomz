import os
import sys
import winreg
import logging
from pathlib import Path
from src.core.config import config

logger = logging.getLogger(__name__)

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "BomzhAssistant"

def _get_launch_command() -> str:
    """Builds the launch command line for silent tray startup with Windows."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    main_py = base_dir / "main.py"
    # Use pythonw if available to start silently in the background tray without a console window
    python_exe = sys.executable
    pythonw = Path(python_exe).parent / "pythonw.exe"
    exe = str(pythonw) if pythonw.exists() else python_exe
    return f'"{exe}" "{main_py}"'

def is_autostart_enabled() -> bool:
    """Checks whether the application is configured to start with Windows in HKCU Run registry."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ) as key:
            try:
                val, _ = winreg.QueryValueEx(key, APP_NAME)
                return bool(val)
            except FileNotFoundError:
                return False
    except Exception as e:
        logger.debug(f"[Autostart] Read registry error: {e}")
        return False

def set_autostart(enable: bool) -> bool:
    """Enables or disables autostart with Windows via HKCU Run registry."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = _get_launch_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                logger.info(f"[Autostart] Enabled: {cmd}")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    logger.info("[Autostart] Disabled")
                except FileNotFoundError:
                    pass
        config.set("autostart", enable)
        return True
    except Exception as e:
        logger.error(f"[Autostart] Write registry error: {e}")
        return False
