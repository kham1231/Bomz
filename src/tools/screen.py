import sys
import logging
from typing import Optional
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtCore import QBuffer, QIODevice

logger = logging.getLogger(__name__)

SCREEN_TRIGGER_KEYWORDS = [
    "экран", "скрин", "посмотри", "взгляни", "глянь",
    "что тут", "что изображено", "что открыто", "что написано",
    "ошибк", "переведи с экрана", "прочитай на экране", "screen"
]

def has_screen_intent(text: str) -> bool:
    """Checks if the user query suggests analyzing what is visible on screen."""
    if not text:
        return False
    lower = text.lower()
    return any(kw in lower for kw in SCREEN_TRIGGER_KEYWORDS)

def capture_screen_bytes(max_width: int = 1280, quality: int = 75) -> bytes:
    """
    Captures primary screen as optimized JPEG bytes in memory (takes ~30-45ms, ~15-40KB).
    Safe to use within PyQt6 application threads.
    """
    app = QApplication.instance()
    if not app:
        # Fallback if called outside GUI event loop
        app = QApplication(sys.argv)

    screen = QGuiApplication.primaryScreen()
    if not screen:
        logger.warning("[ScreenTool] No primary screen detected!")
        return b""

    pixmap = screen.grabWindow(0)
    if pixmap.isNull():
        logger.warning("[ScreenTool] Grabbed pixmap is null!")
        return b""

    if pixmap.width() > max_width:
        pixmap = pixmap.scaledToWidth(max_width)

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "JPEG", quality)
    raw_bytes = buf.data().data()
    buf.close()

    logger.info(f"[ScreenTool] Captured screen: {pixmap.width()}x{pixmap.height()} ({len(raw_bytes)} bytes)")
    return raw_bytes

def take_screenshot(reason: str = "Анализ экрана") -> str:
    """Делает скриншот экрана пользователя и анализирует его содержимое (окна, ошибки, открытый код, текст).
    Вызывай этот инструмент, когда пользователь спрашивает о том, что происходит на компьютере,
    в программе, браузере или просит посмотреть на экран/ошибку, а скриншот не был прикреплен заранее.
    
    Args:
        reason: Причина или цель анализа экрана (например: 'Поиск текста ошибки', 'Анализ открытого окна').
    Returns:
        Текстовый анализ того, что отображено на экране пользователя.
    """
    logger.info(f"[ScreenTool] Gemini autonomously requested take_screenshot: {reason}")
    img_bytes = capture_screen_bytes()
    if not img_bytes:
        return "⚠️ Не удалось захватить экран монитора."

    # Analyze via Gemini Vision
    try:
        from src.services.gemini_service import gemini_service
        vision_analysis = gemini_service.quick_vision_analysis(
            img_bytes,
            prompt=f"Внимательно изучи экран пользователя и ответь на запрос: {reason}. Опиши окна, текст, ошибки или ключевые элементы."
        )
        return f"[Скриншот экрана успешно захвачен]:\n{vision_analysis}"
    except Exception as e:
        logger.error(f"[ScreenTool] Error analyzing screenshot: {e}")
        return f"[Скриншот экрана захвачен ({len(img_bytes)} байт), но возникла ошибка анализа: {e}]"
