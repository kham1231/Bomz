import logging
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QActionGroup

from src.core.config import config
from src.core.autostart import is_autostart_enabled, set_autostart
from src.services.gemini_service import gemini_service
from src.services.tts_service import tts_service, AVAILABLE_SPEAKERS

logger = logging.getLogger(__name__)

def create_tray_icon_pixmap() -> QPixmap:
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QColor(79, 70, 229))
    painter.setPen(QColor(129, 140, 248))
    painter.drawEllipse(4, 4, 56, 56)

    painter.setPen(QColor(255, 255, 255))
    font = QFont("Segoe UI", 26, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), 0x0084, "Б")

    painter.setBrush(QColor(16, 185, 129))
    painter.setPen(QColor(255, 255, 255))
    painter.drawEllipse(44, 44, 16, 16)

    painter.end()
    return pixmap

class BomzhTrayIcon(QSystemTrayIcon):
    """Windows system tray icon with context menu for controls."""
    show_hud_requested = pyqtSignal()
    reset_dialog_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    model_switched = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(QIcon(create_tray_icon_pixmap()))
        self.setToolTip("Ассистент «Бомж» (Ctrl+Shift+Space)")
        self._init_menu()
        self.activated.connect(self._on_tray_activated)

    def _init_menu(self):
        self.menu = QMenu()

        open_action = self.menu.addAction("🤖 Открыть Бомж (Ctrl+Shift+Space)")
        open_action.triggered.connect(self.show_hud_requested.emit)

        self.menu.addSeparator()

        # Models submenu
        self.models_menu = self.menu.addMenu("🧠 Модель Gemini")
        self._populate_models_menu()

        # TTS Submenu
        self.tts_menu = self.menu.addMenu("🔊 Озвучка Silero")
        self._populate_tts_menu()

        self.menu.addSeparator()

        # Autostart option
        self.autostart_action = self.menu.addAction("🚀 Автозапуск при старте Windows")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(is_autostart_enabled())
        self.autostart_action.triggered.connect(lambda checked: set_autostart(checked))

        self.menu.addSeparator()

        reset_action = self.menu.addAction("🔄 Сбросить контекст диалога")
        reset_action.triggered.connect(self.reset_dialog_requested.emit)

        self.menu.addSeparator()

        quit_action = self.menu.addAction("🚪 Выход")
        quit_action.triggered.connect(self.quit_requested.emit)

        self.setContextMenu(self.menu)

    def _populate_models_menu(self):
        self.models_menu.clear()
        active = config.get("active_model", "gemini-3.5-flash-lite")
        models = config.get("available_models", ["gemini-3.5-flash-lite", "gemini-4-hydrogen"])
        
        for model in models:
            action = self.models_menu.addAction(model)
            action.setCheckable(True)
            action.setChecked(model == active)
            action.triggered.connect(lambda checked, m=model: self._select_model(m))

    def _populate_tts_menu(self):
        self.tts_menu.clear()
        
        # Toggle enabled
        is_on = tts_service.is_enabled()
        toggle_action = self.tts_menu.addAction("Включить голос Silero")
        toggle_action.setCheckable(True)
        toggle_action.setChecked(is_on)
        toggle_action.triggered.connect(lambda checked: self._toggle_tts_enabled(checked))

        self.tts_menu.addSeparator()

        # Speaker selection
        current_speaker = tts_service.get_speaker()
        spk_group = QActionGroup(self)
        for spk in AVAILABLE_SPEAKERS:
            act = self.tts_menu.addAction(f"Голос: {spk}")
            act.setCheckable(True)
            act.setChecked(spk == current_speaker)
            spk_group.addAction(act)
            act.triggered.connect(lambda checked, s=spk: self._select_speaker(s))

    def _toggle_tts_enabled(self, enabled: bool):
        tts_service.set_enabled(enabled)
        self._populate_tts_menu()

    def _select_speaker(self, speaker: str):
        tts_service.set_speaker(speaker)
        tts_service.set_enabled(True)
        self._populate_tts_menu()

    def _select_model(self, model_name: str):
        config.set("active_model", model_name)
        gemini_service.set_model(model_name)
        self._populate_models_menu()
        self.model_switched.emit(model_name)
        logger.info(f"[Tray] Switched to model: {model_name}")

    def update_active_model(self, model_name: str):
        self._populate_models_menu()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_hud_requested.emit()
