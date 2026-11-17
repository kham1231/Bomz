import sys
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Win32 Mouse Flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

def _get_user32():
    if sys.platform != "win32":
        return None
    import ctypes
    return ctypes.windll.user32

def get_display_info() -> str:
    """Возвращает разрешение экрана монитора и текущие координаты курсора мыши."""
    user32 = _get_user32()
    if not user32:
        return "⚠️ Доступно только на Windows"

    from ctypes import wintypes, byref
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)

    pt = wintypes.POINT()
    user32.GetCursorPos(byref(pt))

    return f"🖥️ Экран: {w}x{h} пикселей. Текущий курсор мыши: ({pt.x}, {pt.y})."

def mouse_move(x: int, y: int) -> str:
    """Перемещает курсор мыши в указанные координаты (x, y).
    Args:
        x: Горизонтальная координата в пикселях.
        y: Вертикальная координата в пикселях.
    """
    user32 = _get_user32()
    if not user32:
        return "⚠️ Доступно только на Windows"

    user32.SetCursorPos(int(x), int(y))
    return f"🖱️ Курсор перемещен в ({x}, {y})."

def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """Выполняет клик мышью по точным экранным координатам (x, y).
    Args:
        x: Горизонтальная координата в пикселях.
        y: Вертикальная координата в пикселях.
        button: Кнопка мыши ('left', 'right', 'middle').
        clicks: Количество кликов (1 для одиночного, 2 для двойного клика).
    """
    user32 = _get_user32()
    if not user32:
        return "⚠️ Доступно только на Windows"

    btn = button.lower().strip()
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)

    down_flag = MOUSEEVENTF_LEFTDOWN
    up_flag = MOUSEEVENTF_LEFTUP
    if btn == "right":
        down_flag = MOUSEEVENTF_RIGHTDOWN
        up_flag = MOUSEEVENTF_RIGHTUP
    elif btn == "middle":
        down_flag = MOUSEEVENTF_MIDDLEDOWN
        up_flag = MOUSEEVENTF_MIDDLEUP

    for _ in range(clicks):
        user32.mouse_event(down_flag, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(up_flag, 0, 0, 0, 0)
        if clicks > 1:
            time.sleep(0.05)

    click_desc = "Двойной клик" if clicks == 2 else f"Клик ({btn})"
    return f"🖱️ {click_desc} выполнен в точке ({x}, {y})."

def mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int) -> str:
    """Перетаскивает элемент мыши из начальной точки в конечную.
    Args:
        start_x, start_y: Координаты начала перетаскивания.
        end_x, end_y: Координаты завершения перетаскивания.
    """
    user32 = _get_user32()
    if not user32:
        return "⚠️ Доступно только на Windows"

    user32.SetCursorPos(int(start_x), int(start_y))
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)

    # Smooth intermediate steps
    steps = 10
    for s in range(1, steps + 1):
        cur_x = int(start_x + (end_x - start_x) * (s / steps))
        cur_y = int(start_y + (end_y - start_y) * (s / steps))
        user32.SetCursorPos(cur_x, cur_y)
        time.sleep(0.01)

    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return f"🖱️ Перетаскивание из ({start_x}, {start_y}) в ({end_x}, {end_y}) завершено."

def type_text(text: str) -> str:
    """Вводит текстовую строку в активное поле с помощью виртуальной клавиатуры/буфера.
    Args:
        text: Строка текста для ввода.
    """
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    import ctypes
    from src.tools.clipboard import set_clipboard_text
    # Safest and fastest way across any Cyrillic/English characters:
    # Set to clipboard and simulate Ctrl+V
    set_clipboard_text(text)
    time.sleep(0.02)
    user32 = ctypes.windll.user32
    VK_CONTROL = 0x11
    VK_V = 0x56

    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_V, 0, 2, 0)
    user32.keybd_event(VK_CONTROL, 0, 2, 0)

    return f"⌨️ Текст успешно введен: «{text}»"
