import logging
import keyboard
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

class HotkeyListener(QObject):
    """Listens for global hotkeys using keyboard library and dispatches Qt signals."""
    hotkey_triggered = pyqtSignal()

    def __init__(self, hotkey_str: str = "ctrl+shift+space", parent=None):
        super().__init__(parent)
        self.hotkey_str = hotkey_str.lower()
        self._is_registered = False

    def start(self):
        try:
            keyboard.add_hotkey(self.hotkey_str, self._on_hotkey_pressed)
            self._is_registered = True
            logger.info(f"[Hotkey] Registered global hotkey: {self.hotkey_str}")
        except Exception as e:
            logger.error(f"[Hotkey] Failed to register global hotkey {self.hotkey_str}: {e}")

    def stop(self):
        if self._is_registered:
            try:
                keyboard.remove_hotkey(self.hotkey_str)
                self._is_registered = False
            except Exception as e:
                logger.error(f"[Hotkey] Error removing hotkey: {e}")

    def _on_hotkey_pressed(self):
        logger.info(f"[Hotkey] Hotkey triggered: {self.hotkey_str}")
        self.hotkey_triggered.emit()
