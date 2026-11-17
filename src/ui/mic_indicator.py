import math
import logging
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QRectF
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QBrush, QPen, QPainterPath

logger = logging.getLogger(__name__)

class AnimatedMicIndicator(QWidget):
    """
    Compact floating pill widget with vivid glowing pulse, dynamic audio wave bars,
    and a pure vector microphone icon (zero emoji font ghost artifacts).
    Always stays fixed in the TOP-RIGHT corner of the primary screen.
    """
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._drag_pos = None
        self.pulse_phase = 0.0
        self.audio_level = 0.0
        self.displayed_text = "Слушаю..."

        self.setFixedSize(300, 56)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate_pulse)

        self.update_position()

    def _animate_pulse(self):
        self.pulse_phase += 0.14
        if self.pulse_phase > 2 * math.pi:
            self.pulse_phase -= 2 * math.pi
        self.update()

    def _draw_vector_mic(self, painter: QPainter, cx: float, cy: float):
        """Draws a clean, crisp vector microphone icon with zero font/emoji box artifacts."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Capsule (Mic Head)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.setPen(Qt.PenStyle.NoPen)
        capsule_rect = QRectF(cx - 4.5, cy - 9.0, 9.0, 14.0)
        painter.drawRoundedRect(capsule_rect, 4.5, 4.5)

        # 2. Cradle (Arc around capsule)
        cradle_pen = QPen(QColor("#A5B4FC"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(cradle_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cradle_rect = QRectF(cx - 7.5, cy - 6.0, 15.0, 13.0)
        painter.drawArc(cradle_rect, 0 * 16, -180 * 16)

        # 3. Stem
        painter.drawLine(int(cx), int(cy + 7), int(cx), int(cy + 11))

        # 4. Base Foot
        painter.drawLine(int(cx - 5), int(cy + 11), int(cx + 5), int(cy + 11))

        painter.restore()

    def set_audio_level(self, level: float):
        """Sets real-time RMS audio level (0.0 to 1.0) to modulate wave bar height."""
        self.audio_level = max(0.0, min(1.0, float(level)))
        self.update()

    def _draw_audio_waves(self, painter: QPainter, x_start: float, cy: float):
        """Draws dynamic dancing audio visualizer wave bars linked to mic volume."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        num_bars = 4
        bar_width = 3.0
        gap = 2.5
        audio_boost = getattr(self, "audio_level", 0.0) * 16.0
        for i in range(num_bars):
            # Oscillate each bar with offset phases boosted by mic RMS
            factor = (math.sin(self.pulse_phase * 2.2 + i * 1.3) + 1.0) / 2.0
            bar_height = 4.0 + 8.0 * factor + audio_boost * (0.6 + 0.4 * factor)
            bar_height = min(28.0, bar_height)
            bar_x = x_start + i * (bar_width + gap)
            bar_y = cy - bar_height / 2.0

            # Gradient-like color shift
            alpha = int(min(255, 170 + 85 * factor + getattr(self, "audio_level", 0.0) * 70))
            painter.setBrush(QColor(129, 140, 248, alpha))
            painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_width, bar_height), 1.5, 1.5)

        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 1. Total wipe of previous frame
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        pulse = (math.sin(self.pulse_phase) + 1.0) / 2.0
        glow_alpha = int(130 + 120 * pulse)

        # 2. Ambient Soft Glow & Background Pill (zero negative dirty rects, zero DWM warnings)
        rect = self.rect().adjusted(4, 4, -4, -4)
        radius = rect.height() / 2.0

        # Ambient glow layers rendered cleanly within the widget rect
        for offset, alpha_mult in [(3, 0.15), (2, 0.30), (1, 0.55)]:
            glow_rect = rect.adjusted(-offset, -offset, offset, offset)
            glow_r = glow_rect.height() / 2.0
            glow_color = QColor(99, 102, 241, int(glow_alpha * alpha_mult))
            painter.setPen(QPen(glow_color, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(glow_rect, glow_r, glow_r)

        # Background Fill
        painter.setBrush(QColor(18, 22, 34, 248))
        border_color = QColor(129, 140, 248, glow_alpha)
        pen = QPen(border_color, 2.0)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, radius, radius)

        cy = rect.center().y()

        # 3. Vector Mic Icon
        mic_cx = rect.left() + 22.0
        self._draw_vector_mic(painter, mic_cx, cy)

        # 4. Spoken / Dictated Text
        text_font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        painter.setFont(text_font)
        painter.setPen(QColor("#F8FAFC"))

        text_left = mic_cx + 16.0
        text_right = rect.right() - 48.0
        text_rect = QRectF(text_left, rect.top(), max(10.0, text_right - text_left), rect.height())

        metrics = painter.fontMetrics()
        elided = metrics.elidedText(self.displayed_text, Qt.TextElideMode.ElideLeft, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

        # 5. Dynamic Audio Waves
        waves_x = rect.right() - 42.0
        self._draw_audio_waves(painter, waves_x, cy)

        # 6. Pulsing Red Recording Dot with Halo Ring
        dot_cx = rect.right() - 14.0
        # Halo ring
        halo_radius = 4.0 + 4.5 * pulse
        halo_alpha = int(140 * (1.0 - pulse))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(239, 68, 68, halo_alpha), 1.5))
        painter.drawEllipse(QPoint(int(dot_cx), int(cy)), int(halo_radius), int(halo_radius))

        # Solid core red dot
        painter.setBrush(QColor(239, 68, 68, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(int(dot_cx), int(cy)), 3, 3)

        painter.end()

    def update_position(self):
        """Always places the mic pill in the top-right corner of the primary screen."""
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            margin_x = 24
            margin_y = 28
            x = geo.x() + geo.width() - self.width() - margin_x
            y = geo.y() + margin_y
            self.move(x, y)

    def show_listening(self, text: str = "Слушаю..."):
        self.displayed_text = text
        self.update_position()
        self.show()
        self.raise_()
        self.timer.start(33)
        self.update()

    def set_partial_text(self, text: str):
        clean = text.strip()
        self.displayed_text = clean if clean else "Слушаю..."
        self.update()

    def hide_listening(self):
        self.timer.stop()
        self.displayed_text = "Слушаю..."
        self.hide()
