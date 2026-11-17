import sys
import logging
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

def get_clipboard_text() -> str:
    """Считывает текущее текстовое содержимое из буфера обмена Windows.
    Используй этот инструмент, когда пользователь просит проанализировать, объяснить,
    перевести, исправить ошибки или оптимизировать скопированный им текст или код.
    """
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    clipboard = QApplication.clipboard()
    text = clipboard.text()
    if not text or not text.strip():
        return "⚠️ Буфер обмена пуст (в нем нет скопированного текста)."
    logger.info(f"[ClipboardTool] Read {len(text)} characters from clipboard.")
    return f"[Содержимое буфера обмена ({len(text)} симв.)]:\n{text}"

def set_clipboard_text(text: str) -> str:
    """Записывает указанный текст в буфер обмена Windows.
    Используй этот инструмент, когда пользователь просит сохранить результат в буфер обмена,
    скопировать исправленный текст или сгенерированный код.
    Args:
        text: Текст для копирования в буфер обмена.
    """
    if not text:
        return "⚠️ Передан пустой текст для копирования."
    
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        
    clipboard = QApplication.clipboard()
    clipboard.setText(text)
    logger.info(f"[ClipboardTool] Set {len(text)} characters to clipboard.")
    return "📋 Текст успешно скопирован в ваш буфер обмена!"
