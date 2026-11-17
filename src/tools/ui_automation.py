import sys
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

def _ensure_desktop():
    if sys.platform != "win32":
        return
    import ctypes
    try:
        import win32service, win32con
        hdesk = win32service.OpenDesktop("default", 0, False, win32con.MAXIMUM_ALLOWED)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(int(hdesk))
    except Exception:
        pass

def _is_cloaked(hwnd: int) -> bool:
    """Checks whether a window is cloaked/suspended by Windows DWM."""
    if sys.platform != "win32":
        return False
    import ctypes
    cloaked = ctypes.c_int(0)
    # DWMWA_CLOAKED = 14
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0:
        return cloaked.value != 0
    return False

def _safe_control_from_handle(hwnd: int):
    """Safely retrieves a UI Automation control from a window handle without throwing COMErrors."""
    try:
        import uiautomation as auto
        import win32gui
        if not win32gui.IsWindow(hwnd):
            return None
        ctrl = auto.ControlFromHandle(hwnd)
        if ctrl and ctrl.Element:
            return ctrl
    except Exception:
        pass
    return None

def _is_valid_control(ctrl) -> bool:
    if not ctrl:
        return False
    try:
        return ctrl.Element is not None
    except Exception:
        try:
            return ctrl.Exists(0.5)
        except Exception:
            return False

def _get_target_window(title_keyword: Optional[str] = None):
    """Finds target window control by title substring or returns foreground/active window."""
    if sys.platform != "win32":
        return None
    _ensure_desktop()
    import uiautomation as auto
    import win32gui
    import win32service

    # Collect visible, uncloaked windows safely
    visible_windows = []
    def enum_cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and not _is_cloaked(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t:
                visible_windows.append((hwnd, t))
        return True

    try:
        hdesk = win32service.OpenDesktop("default", 0, False, 0x01FF)
        win32gui.EnumDesktopWindows(hdesk, enum_cb, None)
    except Exception:
        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass

    if title_keyword:
        kw = title_keyword.lower().strip()
        matched_hwnd = None
        for hwnd, title in visible_windows:
            if kw in title.lower():
                matched_hwnd = hwnd
                break

        if matched_hwnd:
            try:
                win32gui.SetForegroundWindow(matched_hwnd)
            except Exception:
                pass
            ctrl = _safe_control_from_handle(matched_hwnd)
            if ctrl and _is_valid_control(ctrl):
                return ctrl

        # Fallback via uiautomation root search
        try:
            for child in auto.GetRootControl().GetChildren():
                if kw in (child.Name or "").lower():
                    return child
        except Exception:
            pass

    # Default to foreground window
    fg_hwnd = win32gui.GetForegroundWindow()
    if fg_hwnd and win32gui.IsWindowVisible(fg_hwnd) and not _is_cloaked(fg_hwnd):
        ctrl = _safe_control_from_handle(fg_hwnd)
        if ctrl and _is_valid_control(ctrl):
            return ctrl

    # If foreground window is not an app window (e.g. 0 or desktop), pick top active window
    for hwnd, title in visible_windows:
        if title not in ("Program Manager", "Панель задач", "Taskbar", ""):
            ctrl = _safe_control_from_handle(hwnd)
            if ctrl and _is_valid_control(ctrl):
                return ctrl

    return auto.GetRootControl()

def uia_inspect_window(title_keyword: Optional[str] = None, max_elements: int = 25) -> str:
    """Инспектирует интерфейс активного окна (или окна по названию) через Windows UI Automation.
    Возвращает список интерактивных элементов: кнопок, полей ввода, вкладок, флажков.
    
    Args:
        title_keyword: Название приложения или окна (если не указано, берется активное окно на экране).
        max_elements: Максимальное количество элементов для вывода (по умолчанию 25).
    """
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    try:
        import uiautomation as auto
        target = _get_target_window(title_keyword)
        if not target or not _is_valid_control(target):
            return f"⚠️ Окно '{title_keyword or 'активное'}' не найдено или недоступно."

        win_name = target.Name or "Без названия"
        interesting_types = {
            auto.ControlType.ButtonControl,
            auto.ControlType.EditControl,
            auto.ControlType.CheckBoxControl,
            auto.ControlType.TabItemControl,
            auto.ControlType.MenuItemControl,
            auto.ControlType.ComboBoxControl,
            auto.ControlType.HyperlinkControl,
            auto.ControlType.ListItemControl,
        }

        elements = []
        for ctrl, depth in auto.WalkTree(target, getFirstChild=lambda c: c.GetFirstChildControl(), getNextSibling=lambda c: c.GetNextSiblingControl(), includeTop=False):
            if depth > 5:
                continue
            if ctrl.ControlType in interesting_types or ctrl.Name:
                name = ctrl.Name.strip() if ctrl.Name else ""
                ctrl_type = ctrl.ControlTypeName.replace("Control", "")
                auto_id = ctrl.AutomationId or ""
                rect = ctrl.BoundingRectangle
                if name or auto_id:
                    elements.append({
                        "name": name or "[Нет имени]",
                        "type": ctrl_type,
                        "id": auto_id,
                        "rect": f"({rect.left},{rect.top}..{rect.right},{rect.bottom})" if rect else ""
                    })
                if len(elements) >= max_elements:
                    break

        if not elements:
            return f"Окно: **{win_name}**. Интерактивных UI-элементов стандартного дерева UI Automation не обнаружено."

        lines = [f"🪟 Элементы интерфейса окна «**{win_name}**» ({len(elements)} найдено):"]
        for i, el in enumerate(elements, 1):
            id_str = f" [ID: {el['id']}]" if el['id'] else ""
            lines.append(f"{i}. **{el['name']}** ({el['type']}){id_str} {el['rect']}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[UIA] Inspect error: {e}")
        return f"⚠️ Ошибка UI Automation инспекции: {e}"

def uia_click(control_name: str, control_type: Optional[str] = None, window_title: Optional[str] = None) -> str:
    """Нажимает на элемент интерфейса (кнопку, пункт меню, вкладку) по имени через Windows UI Automation.
    Args:
        control_name: Имя элемента, текст на кнопке или AutomationId (например: 'Сохранить', 'Закрыть', 'Отмена', 'Settings').
        control_type: Тип элемента (например: 'Button', 'MenuItem', 'TabItem') — необязательно.
        window_title: Название окна программы (если не указано, берется текущее окно).
    """
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    try:
        import uiautomation as auto
        target = _get_target_window(window_title)
        if not target or not _is_valid_control(target):
            return f"⚠️ Окно '{window_title or 'активное'}' не найдено."

        target_name_clean = control_name.lower().strip()
        matched_control = None

        for ctrl, depth in auto.WalkTree(target, getFirstChild=lambda c: c.GetFirstChildControl(), getNextSibling=lambda c: c.GetNextSiblingControl(), includeTop=False):
            if depth > 6:
                continue
            name = (ctrl.Name or "").lower().strip()
            auto_id = (ctrl.AutomationId or "").lower().strip()
            if target_name_clean == name or target_name_clean == auto_id or (target_name_clean in name and len(target_name_clean) > 2):
                matched_control = ctrl
                break

        if not matched_control:
            return f"⚠️ Элемент '{control_name}' не найден в окне '{target.Name}'."

        # Try Invoke pattern
        try:
            pattern = matched_control.GetInvokePattern()
            if pattern:
                pattern.Invoke()
                return f"✅ Нажат элемент '{matched_control.Name}' ({matched_control.ControlTypeName}) через Invoke."
        except Exception:
            pass

        # Try Toggle pattern
        try:
            toggle = matched_control.GetTogglePattern()
            if toggle:
                toggle.Toggle()
                return f"✅ Переключен элемент '{matched_control.Name}' ({matched_control.ControlTypeName})."
        except Exception:
            pass

        # Fallback to direct Click
        matched_control.Click(simulateMove=False)
        return f"✅ Выполнен клик по элементу '{matched_control.Name}' ({matched_control.ControlTypeName})."

    except Exception as e:
        logger.error(f"[UIA] Click error for '{control_name}': {e}")
        return f"⚠️ Ошибка нажатия на элемент: {e}"

def uia_set_text(control_name: str, text: str, window_title: Optional[str] = None) -> str:
    """Вводит текст в поле ввода интерфейса программы через Windows UI Automation.
    Args:
        control_name: Имя поля ввода, плейсхолдер или AutomationId (например: 'Поиск', 'Search', 'Имя файла').
        text: Текст для ввода.
        window_title: Название окна программы.
    """
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    try:
        import uiautomation as auto
        target = _get_target_window(window_title)
        if not target or not _is_valid_control(target):
            return f"⚠️ Окно '{window_title or 'активное'}' не найдено."

        target_name_clean = control_name.lower().strip()
        matched_control = None

        for ctrl, depth in auto.WalkTree(target, getFirstChild=lambda c: c.GetFirstChildControl(), getNextSibling=lambda c: c.GetNextSiblingControl(), includeTop=False):
            if depth > 6:
                continue
            name = (ctrl.Name or "").lower().strip()
            auto_id = (ctrl.AutomationId or "").lower().strip()
            if ctrl.ControlType in (auto.ControlType.EditControl, auto.ControlType.DocumentControl, auto.ControlType.ComboBoxControl):
                if target_name_clean in name or target_name_clean in auto_id or not target_name_clean:
                    matched_control = ctrl
                    break

        if not matched_control:
            # Try any edit control
            edit = target.EditControl()
            if edit.Exists(0.5):
                matched_control = edit

        if not matched_control:
            return f"⚠️ Поле ввода '{control_name}' не найдено в окне '{target.Name}'."

        # Set Value via ValuePattern
        try:
            pattern = matched_control.GetValuePattern()
            if pattern:
                pattern.SetValue(text)
                return f"✅ В поле '{matched_control.Name}' введен текст: «{text}»"
        except Exception:
            pass

        # Fallback: SendKeys
        matched_control.Click(simulateMove=False)
        matched_control.SendKeys(text)
        return f"✅ Введено с клавиатуры в '{matched_control.Name}': «{text}»"

    except Exception as e:
        logger.error(f"[UIA] Set text error: {e}")
        return f"⚠️ Ошибка ввода текста: {e}"
