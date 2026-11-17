import sys
import math
import logging
from pynput import mouse
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QTimer, QPoint, QRect, QRectF
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTextBrowser, QApplication,
    QGraphicsDropShadowEffect, QMenu
)
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QAction, QPainter, QBrush, QPen

from src.core.config import config
from src.services.gemini_service import gemini_service
from src.services.tts_service import tts_service, AVAILABLE_SPEAKERS
from src.tools.fast_launcher import try_fast_launch
from src.tools.screen import has_screen_intent, capture_screen_bytes
from src.ui.styles import HUD_STYLESHEET

logger = logging.getLogger(__name__)

class HUDListeningBar(QWidget):
    """
    In-HUD animated listening bar featuring dynamic sound waves and pulsating red recording indicator.
    Directly displayed inside the HUD chat window when voice listening is active.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.pulse_phase = 0.0
        self.audio_level = 0.0
        self.displayed_text = "Слушаю вас... Говорите..."
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)

    def set_audio_level(self, level: float):
        self.audio_level = max(0.0, min(1.0, float(level)))
        self.update()

    def _animate(self):
        self.pulse_phase += 0.14
        if self.pulse_phase > 2 * math.pi:
            self.pulse_phase -= 2 * math.pi
        self.update()

    def start_animation(self, initial_text: str = "Слушаю вас... Говорите..."):
        self.displayed_text = initial_text
        self.show()
        self.timer.start(33)
        self.update()

    def set_text(self, text: str):
        clean = text.strip()
        self.displayed_text = clean if clean else "Слушаю вас... Говорите..."
        self.update()

    def stop_animation(self):
        self.timer.stop()
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        pulse = (math.sin(self.pulse_phase) + 1.0) / 2.0

        # Background pill
        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2.0
        painter.setBrush(QColor(239, 68, 68, 28))
        border_alpha = int(120 + 90 * pulse)
        painter.setPen(QPen(QColor(239, 68, 68, border_alpha), 1.5))
        painter.drawRoundedRect(rect, radius, radius)

        cy = rect.center().y()

        # 1. Pulsing Red Recording Dot with Halo
        dot_cx = rect.left() + 16.0
        halo_r = 3.5 + 4.0 * pulse
        halo_alpha = int(140 * (1.0 - pulse))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(239, 68, 68, halo_alpha), 1.5))
        painter.drawEllipse(QPoint(int(dot_cx), int(cy)), int(halo_r), int(halo_r))

        painter.setBrush(QColor(239, 68, 68, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(int(dot_cx), int(cy)), 3, 3)

        # 2. Spoken / Prompt Text
        text_font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        painter.setFont(text_font)
        painter.setPen(QColor("#F8FAFC"))

        text_left = dot_cx + 14.0
        text_right = rect.right() - 44.0
        text_rect = QRectF(text_left, rect.top(), max(10.0, text_right - text_left), rect.height())

        metrics = painter.fontMetrics()
        elided = metrics.elidedText(self.displayed_text, Qt.TextElideMode.ElideLeft, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

        # 3. Dynamic Audio Equalizer Waves
        waves_x = rect.right() - 36.0
        num_bars = 4
        bar_w = 2.5
        gap = 2.0
        audio_boost = getattr(self, "audio_level", 0.0) * 14.0
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(num_bars):
            factor = (math.sin(self.pulse_phase * 2.2 + i * 1.3) + 1.0) / 2.0
            h = 4.0 + 8.0 * factor + audio_boost * (0.6 + 0.4 * factor)
            h = min(24.0, h)
            bx = waves_x + i * (bar_w + gap)
            by = cy - h / 2.0
            alpha = int(min(255, 160 + 95 * factor + getattr(self, "audio_level", 0.0) * 70))
            painter.setBrush(QColor(248, 113, 113, alpha))
            painter.drawRoundedRect(QRectF(bx, by, bar_w, h), 1.2, 1.2)

        painter.end()

class GeminiStreamWorker(QThread):
    """Worker thread to stream Gemini API response asynchronously without freezing Qt GUI."""
    token_received = pyqtSignal(str)
    stream_finished = pyqtSignal()
    stream_error = pyqtSignal(str)
    activity_updated = pyqtSignal(str)

    def __init__(
        self,
        prompt: str = "",
        audio_bytes: bytes = None,
        fallback_text: str = "",
        screenshot_bytes: bytes = None,
        parent=None
    ):
        super().__init__(parent)
        self.prompt = prompt
        self.audio_bytes = audio_bytes
        self.fallback_text = fallback_text
        self.screenshot_bytes = screenshot_bytes
        self._is_stopped = False

    def stop(self):
        """Signals the worker to abort streaming cleanly."""
        self._is_stopped = True

    def _safe_activity(self, text: str):
        if not self._is_stopped:
            self.activity_updated.emit(text)

    def run(self):
        try:
            if self.audio_bytes:
                stream = gemini_service.stream_audio_prompt(
                    self.audio_bytes,
                    fallback_text=self.fallback_text,
                    screenshot_bytes=self.screenshot_bytes,
                    activity_callback=self._safe_activity
                )
            else:
                stream = gemini_service.stream_prompt(
                    self.prompt,
                    screenshot_bytes=self.screenshot_bytes,
                    activity_callback=self._safe_activity
                )
            for chunk in stream:
                if self._is_stopped:
                    break
                self.token_received.emit(chunk)
            if not self._is_stopped:
                self.stream_finished.emit()
        except Exception as e:
            if not self._is_stopped:
                self.stream_error.emit(str(e))

class HUDWindow(QWidget):
    """
    Floating, translucent, frameless HUD overlay window.
    Features:
    - Integrated In-HUD voice listening state with dynamic equalizer waves and pulsating red indicator.
    - One-line dynamic tool activity banner (shows active commands and tools in real time).
    - Elegant fade & slide appearance.
    - Animated glowing thinking loader (pulsating dots) while waiting for first token.
    - Silero TTS voice toggle & speaker selector.
    - Global click-outside auto-hide via pynput.
    - Window dragging and pinned mode (📌/📍).
    """
    model_changed = pyqtSignal(str)
    manual_listen_requested = pyqtSignal()
    response_completed = pyqtSignal()
    tts_playback_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hudWindow")
        
        self.window_width = config.get("window_width", 440)
        self.min_height = 140
        self.max_height = config.get("window_max_height", 650)
        self.current_height = self.min_height
        
        self.response_text = ""
        self.stream_worker = None
        self.is_streaming = False
        self.is_recording_voice = False
        self._drag_pos = None
        self.first_token_received = False
        self.query_extracted = True
        self.header_buffer = ""
        self.fallback_query = ""
        
        self.is_pinned = config.get("pin_window", False)
        self.mouse_listener = None

        # Thread-safe TTS finished handler executed strictly in main GUI event loop
        self.tts_playback_finished.connect(self._on_tts_playback_finished, Qt.ConnectionType.QueuedConnection)

        # Animated thinking dots
        self.thinking_frame = 0
        self.thinking_timer = QTimer(self)
        self.thinking_timer.timeout.connect(self._animate_thinking_loader)

        self._init_window_flags()
        self._init_ui()
        self.update_position()

    def _init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(HUD_STYLESHEET)

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        self.container = QWidget(self)
        self.container.setObjectName("centralWidget")
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(16, 14, 16, 14)
        container_layout.setSpacing(10)

        # --- Top Header Bar ---
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.title_label = QLabel("🤖 Бомж", self.container)
        self.title_label.setObjectName("titleLabel")
        header_layout.addWidget(self.title_label)

        self.status_badge = QLabel("🟢 Готов", self.container)
        self.status_badge.setObjectName("statusBadge")
        header_layout.addWidget(self.status_badge)

        header_layout.addStretch()

        # Model Selector Chip
        active_model = config.get("active_model", "gemini-3.5-flash-lite")
        self.model_chip = QPushButton(self._format_model_name(active_model), self.container)
        self.model_chip.setObjectName("modelChip")
        self.model_chip.setToolTip("Кликните для переключения: 3.5 Lite <-> 4 Hydrogen")
        self.model_chip.clicked.connect(self._on_toggle_model)
        header_layout.addWidget(self.model_chip)

        # TTS Voice Toggle Button
        tts_on = tts_service.is_enabled()
        self.tts_btn = QPushButton("🔊" if tts_on else "🔇", self.container)
        self.tts_btn.setObjectName("iconButton")
        self.tts_btn.setToolTip(f"Озвучка Silero (Клик: вкл/выкл, Текущий голос: {tts_service.get_speaker()})")
        self.tts_btn.clicked.connect(self._toggle_tts)
        self.tts_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tts_btn.customContextMenuRequested.connect(self._show_tts_menu)
        header_layout.addWidget(self.tts_btn)

        # Pin / Unpin Button
        pin_icon = "📌" if self.is_pinned else "📍"
        self.pin_btn = QPushButton(pin_icon, self.container)
        self.pin_btn.setObjectName("iconButton")
        tip = "📌 Закреплено (не скрывается при клике мимо)" if self.is_pinned else "📍 Автоскрытие (скрывается при клике мимо)"
        self.pin_btn.setToolTip(tip)
        self.pin_btn.clicked.connect(self._toggle_pin)
        header_layout.addWidget(self.pin_btn)

        # Copy Button
        self.copy_btn = QPushButton("📋", self.container)
        self.copy_btn.setObjectName("iconButton")
        self.copy_btn.setToolTip("Скопировать ответ")
        self.copy_btn.clicked.connect(self._copy_response)
        header_layout.addWidget(self.copy_btn)

        # Stop Button (Immediate Abort of Execution and Speech)
        self.stop_btn = QPushButton("🛑", self.container)
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setToolTip("Остановить всё (Esc, 'Стоп')")
        self.stop_btn.clicked.connect(lambda: self.stop_all(notify_user=True))
        header_layout.addWidget(self.stop_btn)

        # Reset Button
        self.reset_btn = QPushButton("🔄", self.container)
        self.reset_btn.setObjectName("iconButton")
        self.reset_btn.setToolTip("Новый диалог (очистить)")
        self.reset_btn.clicked.connect(self.reset_dialog)
        header_layout.addWidget(self.reset_btn)

        # Close Button
        self.close_btn = QPushButton("✕", self.container)
        self.close_btn.setObjectName("iconButton")
        self.close_btn.setToolTip("Закрыть (Esc)")
        self.close_btn.clicked.connect(self.hide)
        header_layout.addWidget(self.close_btn)

        container_layout.addLayout(header_layout)

        # --- Input Field ---
        input_layout = QHBoxLayout()
        self.prompt_input = QLineEdit(self.container)
        self.prompt_input.setObjectName("promptInput")
        self.prompt_input.setPlaceholderText("Спроси или скажи «Бомж»...")
        self.prompt_input.returnPressed.connect(self._on_user_submit_typed)
        input_layout.addWidget(self.prompt_input)

        self.mic_btn = QPushButton("🎙️", self.container)
        self.mic_btn.setObjectName("iconButton")
        self.mic_btn.setToolTip("Диктовать голосом")
        self.mic_btn.clicked.connect(self._on_mic_clicked)
        input_layout.addWidget(self.mic_btn)

        container_layout.addLayout(input_layout)

        # --- In-HUD Dynamic Voice Listening Bar ---
        self.listening_bar = HUDListeningBar(self.container)
        self.listening_bar.hide()
        container_layout.addWidget(self.listening_bar)

        # --- Single-line Dynamic Tool Activity Banner ---
        self.activity_banner = QLabel(self.container)
        self.activity_banner.setObjectName("activityBanner")
        self.activity_banner.hide()
        container_layout.addWidget(self.activity_banner)

        # --- Dynamic Response Area ---
        self.response_browser = QTextBrowser(self.container)
        self.response_browser.setObjectName("responseBrowser")
        self.response_browser.setOpenExternalLinks(True)
        self.response_browser.hide()
        container_layout.addWidget(self.response_browser)

        root_layout.addWidget(self.container)
        self.resize(self.window_width, self.min_height)

    def _format_model_name(self, model: str) -> str:
        if "3.5-flash-lite" in model or "flash-lite" in model:
            return "⚡ 3.5 Lite"
        elif "hydrogen" in model:
            return "🚀 4 Hydrogen"
        return model.replace("models/", "").replace("gemini-", "")

    def _toggle_tts(self):
        new_state = not tts_service.is_enabled()
        tts_service.set_enabled(new_state)
        self.tts_btn.setText("🔊" if new_state else "🔇")
        speaker = tts_service.get_speaker()
        tip = f"Озвучка Silero (ВКЛ: {speaker})" if new_state else f"Озвучка Silero (ВЫКЛ: {speaker})"
        self.tts_btn.setToolTip(tip)
        status_txt = f"Озвучка: {speaker}" if new_state else "Озвучка выкл"
        self.set_status(status_txt, "ready")
        if new_state:
            tts_service.speak("Голос включен")
        else:
            tts_service.stop()
        QTimer.singleShot(1500, lambda: self.set_status("Готов", "ready"))

    def _show_tts_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e2238;
                color: #f1f5f9;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #4f46e5;
            }
        """)
        current_spk = tts_service.get_speaker()
        for spk in AVAILABLE_SPEAKERS:
            action = menu.addAction(f"{spk} {'✓' if spk == current_spk else ''}")
            action.triggered.connect(lambda ch, s=spk: self._select_speaker(s))
        menu.exec(self.tts_btn.mapToGlobal(pos))

    def _select_speaker(self, speaker_name: str):
        tts_service.set_speaker(speaker_name)
        tts_service.set_enabled(True)
        self.tts_btn.setText("🔊")
        self.tts_btn.setToolTip(f"Озвучка Silero (ВКЛ: {speaker_name})")
        self.set_status(f"Голос: {speaker_name}", "ready")
        tts_service.speak(f"Выбран голос {speaker_name}")
        QTimer.singleShot(1500, lambda: self.set_status("Готов", "ready"))

    def _toggle_pin(self):
        self.is_pinned = not self.is_pinned
        config.set("pin_window", self.is_pinned)
        self.pin_btn.setText("📌" if self.is_pinned else "📍")
        tip = "📌 Закреплено (не закрывается при клике мимо)" if self.is_pinned else "📍 Автозакрытие при клике мимо"
        self.pin_btn.setToolTip(tip)
        self.set_status("Закреплено" if self.is_pinned else "Автозакрытие", "ready")
        QTimer.singleShot(1200, lambda: self.set_status("Готов", "ready"))

        if self.is_pinned:
            self._stop_mouse_listener()
        else:
            self._start_mouse_listener()

    def _start_mouse_listener(self):
        if self.mouse_listener is None and not self.is_pinned:
            try:
                self.mouse_listener = mouse.Listener(on_click=self._on_global_click)
                self.mouse_listener.daemon = True
                self.mouse_listener.start()
            except Exception as e:
                logger.error(f"[HUD] Error starting mouse listener: {e}")

    def _stop_mouse_listener(self):
        if self.mouse_listener:
            try:
                self.mouse_listener.stop()
            except Exception:
                pass
            self.mouse_listener = None

    def _on_global_click(self, x, y, button, pressed):
        if pressed and not self.is_pinned and self.isVisible():
            geo = self.geometry()
            if not (geo.left() <= x <= geo.right() and geo.top() <= y <= geo.bottom()):
                QTimer.singleShot(0, self.hide)

    def _on_tts_playback_finished(self):
        """Called safely in the main Qt GUI thread when TTS audio playback concludes."""
        if not self.is_streaming:
            QTimer.singleShot(150, self.response_completed.emit)

    def _stop_stream_worker(self):
        """Safely stops active streaming worker thread and detaches all event signals."""
        if self.stream_worker and self.stream_worker.isRunning():
            try:
                self.stream_worker.stop()
                try:
                    self.stream_worker.token_received.disconnect()
                except Exception:
                    pass
                try:
                    self.stream_worker.activity_updated.disconnect()
                except Exception:
                    pass
                try:
                    self.stream_worker.stream_finished.disconnect()
                except Exception:
                    pass
                try:
                    self.stream_worker.stream_error.disconnect()
                except Exception:
                    pass
                self.stream_worker.quit()
                if not self.stream_worker.wait(250):
                    self.stream_worker.terminate()
                    self.stream_worker.wait(150)
            except Exception as e:
                logger.debug(f"[HUD] Worker stop error: {e}")

    def stop_all(self, notify_user: bool = True):
        """Immediately interrupts streaming, tool execution, thinking loader, and audio playback."""
        was_active = self.is_streaming or self.is_recording_voice or tts_service.is_playing()
        self.is_streaming = False
        self._stop_stream_worker()
        self.thinking_timer.stop()
        self.stop_listening_ui()
        tts_service.stop()
        self.activity_banner.hide()
        self.set_status("Остановлено", "ready")

        if was_active:
            if self.response_text:
                self.response_text += "\n\n🛑 *Остановлено пользователем.*"
            else:
                self.response_text = "🛑 *Выполнение остановлено.*"
            self.response_browser.clear()
            self.response_browser.show()
            self.response_browser.setMarkdown(self.response_text)
            self._adjust_window_height_downwards()
            if notify_user and tts_service.is_enabled():
                tts_service.speak("Остановлено")
            logger.info("[HUD] Immediate stop executed.")
        else:
            self.set_status("Готов", "ready")

    def hide(self):
        self._stop_mouse_listener()
        self.thinking_timer.stop()
        self.stop_listening_ui()
        tts_service.stop()
        self.activity_banner.hide()
        self._stop_stream_worker()
        super().hide()

    def closeEvent(self, event):
        self._stop_mouse_listener()
        self.thinking_timer.stop()
        self.stop_listening_ui()
        tts_service.stop()
        self.activity_banner.hide()
        self._stop_stream_worker()
        super().closeEvent(event)

    def update_position(self):
        saved_x = config.get("saved_x")
        saved_y = config.get("saved_y")
        if saved_x is not None and saved_y is not None:
            self.move(int(saved_x), int(saved_y))
            return

        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        margin_x = 24
        margin_y = 28
        x = geo.x() + geo.width() - self.window_width - margin_x
        y = geo.y() + margin_y
        self.move(x, y)

    def set_status(self, text: str, status_type: str = "ready"):
        icons = {
            "ready": "🟢",
            "listening": "🔴",
            "thinking": "🧠",
            "streaming": "⚡",
            "tool": "⚙️",
            "error": "⚠️"
        }
        icon = icons.get(status_type, "🟢")
        self.status_badge.setText(f"{icon} {text}")

    def is_listening_ui_active(self) -> bool:
        return self.is_recording_voice

    def start_listening_ui(self, initial_text: str = "Слушаю вас... Говорите..."):
        """Activates in-HUD voice listening animation without closing the chat window."""
        self.is_recording_voice = True
        self.set_status("Слушаю...", "listening")
        self.prompt_input.clear()
        self.prompt_input.setPlaceholderText("🎙️ Идет запись голоса...")
        self.listening_bar.start_animation(initial_text)
        self._adjust_window_height_downwards()
        self.show()
        self.raise_()

    def stop_listening_ui(self):
        """Stops in-HUD voice listening animation."""
        self.is_recording_voice = False
        self.listening_bar.stop_animation()
        self.prompt_input.setPlaceholderText("Спроси или скажи «Бомж»...")
        if "Слушаю" in self.status_badge.text():
            self.set_status("Готов", "ready")
        self._adjust_window_height_downwards()

    def set_dictated_text(self, text: str):
        clean = text.strip()
        if clean:
            self.listening_bar.set_text(clean)
            self.prompt_input.setText(clean)
        self.set_status("Слушаю...", "listening")

    def prepare_for_new_wake_word(self):
        self.thinking_timer.stop()
        self.stop_listening_ui()
        tts_service.stop()
        self._stop_stream_worker()
        self.activity_banner.hide()
        self.response_text = ""
        self.response_browser.clear()
        self.response_browser.hide()
        self.prompt_input.clear()
        self.current_height = self.min_height
        self.resize(self.window_width, self.min_height)
        self.set_status("Слушаю...", "listening")

    def show_hud(
        self,
        query: str = None,
        audio_bytes: bytes = None,
        fallback_query: str = "",
        start_listen: bool = False,
        animate: bool = True
    ):
        self.update_position()
        self.show()
        self.raise_()
        self.activateWindow()

        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
            except Exception:
                pass

        if animate:
            self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
            self.fade_anim.setDuration(180)
            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(1.0)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.fade_anim.start()
        else:
            self.setWindowOpacity(1.0)

        if not self.is_pinned:
            self._start_mouse_listener()

        if audio_bytes:
            self.send_audio_query(audio_bytes, fallback_query)
        elif query:
            self.send_query(query)
        elif start_listen:
            self.start_listening_ui()
        else:
            self.prompt_input.setFocus()

    def _on_user_submit_typed(self):
        text = self.prompt_input.text().strip()
        if text:
            self.stop_listening_ui()
            self.send_query(text)

    def _on_mic_clicked(self):
        self.start_listening_ui()
        self.manual_listen_requested.emit()

    def send_query(self, query: str):
        if not query.strip():
            return

        self.stop_listening_ui()
        self._stop_stream_worker()
        tts_service.stop()
        if tts_service.is_enabled():
            tts_service.playback_finished_callback = self.tts_playback_finished.emit
            tts_service.start_stream_session()

        # Check instant fast launch for direct atomic queries (e.g. "открой настройки", "звук 50%")
        # Composite queries ("открой калькулятор и посчитай 2+2") pass through to Gemini!
        fast_note = try_fast_launch(query)
        if fast_note:
            if fast_note == "[STOP]":
                self.stop_all(notify_user=True)
                return
            self.is_streaming = False
            self.first_token_received = True
            self.thinking_timer.stop()
            self.activity_banner.hide()
            self.prompt_input.setText(query)
            self.response_text = fast_note
            self.response_browser.clear()
            self.response_browser.show()
            self.response_browser.setMarkdown(f"✅ {fast_note}")
            self.set_status("Готов", "ready")
            self._adjust_window_height_downwards()
            if tts_service.is_enabled():
                tts_service.playback_finished_callback = self.tts_playback_finished.emit
                tts_service.speak(fast_note)
            else:
                QTimer.singleShot(300, self.response_completed.emit)
            return

        # Check upfront screen vision intent
        screenshot_bytes = None
        if has_screen_intent(query):
            screenshot_bytes = capture_screen_bytes()

        self.is_streaming = True
        self.first_token_received = False
        self.query_extracted = True
        self.header_buffer = ""
        self.fallback_query = ""
        status_txt = "📷 Анализирую экран..." if screenshot_bytes else "Думаю..."
        self.set_status(status_txt, "tool" if screenshot_bytes else "thinking")
        
        self.prompt_input.setText(query)
        self.response_text = ""
        self.response_browser.show()
        self.activity_banner.hide()
        
        # Start thinking animation
        self.thinking_frame = 0
        self._animate_thinking_loader()
        self.thinking_timer.start(240)

        self.current_height = self.min_height + 50
        self.resize(self.window_width, self.current_height)

        self.stream_worker = GeminiStreamWorker(prompt=query, screenshot_bytes=screenshot_bytes)
        self.stream_worker.token_received.connect(self._on_token_received)
        self.stream_worker.activity_updated.connect(self._on_activity_updated)
        self.stream_worker.stream_finished.connect(self._on_stream_finished)
        self.stream_worker.stream_error.connect(self._on_stream_error)
        self.stream_worker.start()

    def send_audio_query(self, audio_bytes: bytes, fallback_query: str = ""):
        self.stop_listening_ui()
        self._stop_stream_worker()
        tts_service.stop()

        # If atomic speech fallback query matches local hardware semantic intent, execute immediately without Gemini!
        # Composite speech queries will pass through to Gemini with multi-tool chaining
        if fallback_query:
            fast_note = try_fast_launch(fallback_query)
            if fast_note:
                if fast_note == "[STOP]":
                    self.stop_all(notify_user=True)
                    return
                self.is_streaming = False
                self.first_token_received = True
                self.thinking_timer.stop()
                self.activity_banner.hide()
                self.prompt_input.setText(f"🎙️ {fallback_query}")
                self.response_text = fast_note
                self.response_browser.clear()
                self.response_browser.show()
                self.response_browser.setMarkdown(f"✅ {fast_note}")
                self.set_status("Готов", "ready")
                self._adjust_window_height_downwards()
                if tts_service.is_enabled():
                    tts_service.playback_finished_callback = self.tts_playback_finished.emit
                    tts_service.speak(fast_note)
                else:
                    QTimer.singleShot(300, self.response_completed.emit)
                return

        if tts_service.is_enabled():
            tts_service.playback_finished_callback = self.tts_playback_finished.emit
            tts_service.start_stream_session()

        # Check upfront screen vision intent from speech fallback/partial
        screenshot_bytes = None
        if has_screen_intent(fallback_query):
            screenshot_bytes = capture_screen_bytes()

        self.is_streaming = True
        self.first_token_received = False
        self.query_extracted = False
        self.header_buffer = ""
        self.fallback_query = fallback_query
        
        status_txt = "📷 Вижу экран, слушаю..." if screenshot_bytes else "Слушаю ответ..."
        self.set_status(status_txt, "tool" if screenshot_bytes else "thinking")
        self.prompt_input.setText("🎙️ Распознаю голос..." if not fallback_query else f"🎙️ {fallback_query}")
        self.response_text = ""
        self.response_browser.show()
        self.activity_banner.hide()

        # Start thinking animation
        self.thinking_frame = 0
        self._animate_thinking_loader()
        self.thinking_timer.start(240)

        self.current_height = self.min_height + 50
        self.resize(self.window_width, self.current_height)

        self.stream_worker = GeminiStreamWorker(
            audio_bytes=audio_bytes,
            fallback_text=fallback_query,
            screenshot_bytes=screenshot_bytes
        )
        self.stream_worker.token_received.connect(self._on_token_received)
        self.stream_worker.activity_updated.connect(self._on_activity_updated)
        self.stream_worker.stream_finished.connect(self._on_stream_finished)
        self.stream_worker.stream_error.connect(self._on_stream_error)
        self.stream_worker.start()

    def _on_activity_updated(self, text: str):
        """Displays real-time one-line tool activity banner."""
        if text.strip():
            max_len = 54
            display_text = text if len(text) <= max_len else text[:51] + "..."
            self.activity_banner.setText(display_text)
            self.activity_banner.show()
            self.set_status("Выполняю...", "tool")
            self._adjust_window_height_downwards()
        else:
            self.activity_banner.hide()
            self._adjust_window_height_downwards()

    def _animate_thinking_loader(self):
        if self.first_token_received:
            return

        dots = [
            "<span style='color:#818CF8;'>●</span> <span style='color:#334155;'>○</span> <span style='color:#334155;'>○</span>",
            "<span style='color:#334155;'>○</span> <span style='color:#818CF8;'>●</span> <span style='color:#334155;'>○</span>",
            "<span style='color:#334155;'>○</span> <span style='color:#334155;'>○</span> <span style='color:#818CF8;'>●</span>"
        ]
        active_dots = dots[self.thinking_frame % len(dots)]
        self.thinking_frame += 1

        html = f"""
        <div style='padding: 12px 6px; font-family: Segoe UI, sans-serif; font-size: 14px; color: #94A3B8;'>
            <span style='font-size: 16px; font-weight: bold;'>{active_dots}</span> &nbsp;&nbsp;<b style='color: #E2E8F0;'>Бомж думает...</b>
        </div>
        """
        self.response_browser.setHtml(html)

    def _on_token_received(self, token: str):
        if not self.query_extracted:
            self.header_buffer += token
            if "\n" in self.header_buffer:
                first_line, rest = self.header_buffer.split("\n", 1)
                if "QUERY:" in first_line:
                    extracted = first_line.split("QUERY:", 1)[1].strip()
                    if extracted.startswith("[") and extracted.endswith("]"):
                        extracted = extracted[1:-1].strip()
                    if extracted:
                        self.prompt_input.setText(extracted)
                    elif self.fallback_query:
                        self.prompt_input.setText(self.fallback_query)
                elif self.fallback_query:
                    self.prompt_input.setText(self.fallback_query)
                self.query_extracted = True
                token = rest
                if not token:
                    return
            else:
                if len(self.header_buffer) > 80 and "QUERY:" not in self.header_buffer:
                    self.query_extracted = True
                    if self.fallback_query:
                        self.prompt_input.setText(self.fallback_query)
                    token = self.header_buffer
                else:
                    return

        if not self.first_token_received:
            self.first_token_received = True
            self.thinking_timer.stop()
            self.activity_banner.hide()
            self.response_browser.clear()

        self.set_status("Печатаю...", "streaming")
        self.response_text += token
        self.response_browser.setMarkdown(self.response_text)

        # Stream tokens to TTS in real time
        if tts_service.is_enabled():
            tts_service.feed_stream_token(token)
        
        scrollbar = self.response_browser.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        self._adjust_window_height_downwards()

    def _adjust_window_height_downwards(self):
        doc_height = int(self.response_browser.document().size().height())
        header_and_input_height = 110
        listening_extra = 38 if self.listening_bar.isVisible() else 0
        activity_extra = 34 if self.activity_banner.isVisible() else 0
        padding = 40
        needed_height = header_and_input_height + listening_extra + activity_extra + doc_height + padding

        target_height = max(self.min_height, min(needed_height, self.max_height))
        if target_height != self.current_height:
            self.current_height = target_height
            self.resize(self.window_width, self.current_height)

    def _on_stream_finished(self):
        self.is_streaming = False
        self.thinking_timer.stop()
        self.activity_banner.hide()
        self.stop_listening_ui()

        if not self.query_extracted and self.header_buffer:
            if "QUERY:" in self.header_buffer:
                parts = self.header_buffer.split("\n", 1)
                first_line = parts[0]
                rest = parts[1] if len(parts) > 1 else ""
                extracted = first_line.split("QUERY:", 1)[1].strip()
                if extracted.startswith("[") and extracted.endswith("]"):
                    extracted = extracted[1:-1].strip()
                if extracted:
                    self.prompt_input.setText(extracted)
                self.response_text = rest.strip()
            else:
                if self.fallback_query:
                    self.prompt_input.setText(self.fallback_query)
                self.response_text = self.header_buffer
            if self.response_text:
                self.response_browser.clear()
                self.response_browser.setMarkdown(self.response_text)
            self.query_extracted = True

        self.set_status("Готов", "ready")
        self._adjust_window_height_downwards()
        
        if tts_service.is_enabled() and self.response_text:
            tts_service.finish_stream_session()
        else:
            QTimer.singleShot(250, self.response_completed.emit)

    def _on_stream_error(self, err_msg: str):
        self.is_streaming = False
        self.thinking_timer.stop()
        self.activity_banner.hide()
        self.stop_listening_ui()
        tts_service.stop()
        self.set_status("Ошибка", "error")
        self.response_text += f"\n\n⚠️ {err_msg}"
        self.response_browser.setMarkdown(self.response_text)
        self._adjust_window_height_downwards()

    def _on_toggle_model(self):
        new_model = config.toggle_model()
        gemini_service.set_model(new_model)
        self.model_chip.setText(self._format_model_name(new_model))
        self.model_changed.emit(new_model)
        logger.info(f"[HUD] Active model switched to: {new_model}")

    def update_model_chip(self, model_name: str):
        self.model_chip.setText(self._format_model_name(model_name))

    def _copy_response(self):
        if self.response_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.response_text)
            self.set_status("Скопировано!", "ready")
            QTimer.singleShot(1500, lambda: self.set_status("Готов", "ready"))

    def reset_dialog(self):
        self.thinking_timer.stop()
        self.stop_listening_ui()
        tts_service.stop()
        self._stop_stream_worker()
        self.activity_banner.hide()
        gemini_service.start_new_chat(config.get("active_model"))
        self.response_text = ""
        self.response_browser.clear()
        self.response_browser.hide()
        self.prompt_input.clear()
        self.prompt_input.setPlaceholderText("Спроси или скажи «Бомж»...")
        self.current_height = self.min_height
        self.resize(self.window_width, self.min_height)
        self.set_status("Готов", "ready")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            child = self.childAt(pos)
            if child in (self.prompt_input, self.response_browser):
                super().mousePressEvent(event)
                return
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)
            config.set("saved_x", new_pos.x())
            config.set("saved_y", new_pos.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.is_streaming or tts_service.is_playing():
                self.stop_all(notify_user=False)
            else:
                tts_service.stop()
                self.hide()
        else:
            super().keyPressEvent(event)
