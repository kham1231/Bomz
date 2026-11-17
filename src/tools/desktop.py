import sys
import time
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Virtual key codes on Windows
VK_LWIN = 0x5B
VK_MENU = 0x12       # Alt
VK_F4 = 0x73         # F4
VK_UP = 0x26
VK_DOWN = 0x28
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

def _send_key_combo(*keys):
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    for k in keys:
        user32.keybd_event(k, 0, 0, 0)
    time.sleep(0.04)
    for k in reversed(keys):
        user32.keybd_event(k, 0, 2, 0)

def _get_pycaw_endpoint():
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    try:
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        return speakers.EndpointVolume
    except Exception as e:
        logger.warning(f"[DesktopTool] pycaw GetSpeakers failed: {e}")
        return None

def get_master_volume_percent() -> int:
    """Gets current master volume percentage (0 - 100)."""
    ep = _get_pycaw_endpoint()
    if ep:
        try:
            val = ep.GetMasterVolumeLevelScalar()
            return int(round(val * 100))
        except Exception:
            pass
    return 50

def set_master_volume_percent(percent) -> str:
    """Sets master volume directly to an exact percentage (0 - 100%)."""
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    try:
        p = max(0, min(100, int(round(float(percent)))))
    except (ValueError, TypeError):
        return f"⚠️ Неверный уровень громкости: {percent}"

    ep = _get_pycaw_endpoint()
    if ep:
        try:
            if p > 0:
                if ep.GetMute():
                    ep.SetMute(0, None)
            else:
                ep.SetMute(1, None)
            ep.SetMasterVolumeLevelScalar(p / 100.0, None)
            logger.info(f"[DesktopTool] Exact master volume set to {p}% via Core Audio endpoint")
            return f"🔊 Громкость установлена на {p}%"
        except Exception as e:
            logger.error(f"[DesktopTool] Error setting volume via pycaw: {e}")

    # Fallback to keybd_event if pycaw fails
    return f"⚠️ Не удалось установить точную громкость ({p}%)"

def change_volume(action: str = "up", level: Optional[int] = None) -> str:
    """Управляет громкостью звука в Windows.
    Args:
        action: 'up' (сделать громче), 'down' (сделать тише), 'mute' (выключить звук), 'unmute' (включить звук), 'set' (установить на точный процент).
        level: Точный уровень громкости от 0 до 100 процентов (например: 20, 50, 80).
    """
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    # 1. Exact level argument provided
    if level is not None:
        return set_master_volume_percent(level)

    action_clean = str(action).lower().strip()

    # 2. Check if action string contains numbers (e.g. "50%", "50", "set 30")
    num_match = re.search(r'\d+', action_clean)
    if num_match:
        val = int(num_match.group())
        if 0 <= val <= 100:
            return set_master_volume_percent(val)

    if action_clean in ("максимум", "на максимум", "на всю", "на полную", "100%", "max"):
        return set_master_volume_percent(100)
    if action_clean in ("минимум", "на минимум", "в ноль", "на ноль", "0%", "min"):
        return set_master_volume_percent(0)

    # 3. Mute / Unmute
    ep = _get_pycaw_endpoint()
    if action_clean in ("mute", "выключи звук", "заглуши", "мьют", "без звука", "выключить"):
        if ep:
            try:
                ep.SetMute(1, None)
                return "🔇 Режим звука выключен (Mute)"
            except Exception:
                pass
        import ctypes
        ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
        return "🔇 Режим звука переключен (Mute)"

    if action_clean in ("unmute", "включи звук", "верни звук", "размьють", "включить"):
        if ep:
            try:
                ep.SetMute(0, None)
                return "🔊 Звук включен (Unmute)"
            except Exception:
                pass
        import ctypes
        ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
        return "🔊 Звук включен"

    # 4. Louder (+10%)
    if action_clean in ("up", "louder", "громче", "прибавь", "погромче", "увеличь"):
        curr = get_master_volume_percent()
        new_val = min(100, curr + 10)
        set_master_volume_percent(new_val)
        return f"🔊 Громкость увеличена (+10% → {new_val}%)"

    # 5. Quieter (-10%)
    if action_clean in ("down", "quieter", "тише", "убавь", "потише", "уменьши"):
        curr = get_master_volume_percent()
        new_val = max(0, curr - 10)
        set_master_volume_percent(new_val)
        return f"🔉 Громкость уменьшена (-10% → {new_val}%)"

    return f"⚠️ Неизвестное действие с громкостью: {action}"

def media_control(action: str = "play_pause") -> str:
    """Управляет воспроизведением мультимедиа (музыка, видео в плеере или браузере).
    Args:
        action: 'play_pause' (воспроизведение/пауза), 'next' (следующий трек), 'prev' (предыдущий трек), 'stop' (остановить).
    """
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    import ctypes
    user32 = ctypes.windll.user32
    act = action.lower().strip()

    if act in ("play_pause", "play", "pause", "пауза", "плей", "пуск", "играть"):
        user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)
        return "⏯️ Воспроизведение / Пауза переключено"
    elif act in ("next", "следующий", "вперед"):
        user32.keybd_event(VK_MEDIA_NEXT_TRACK, 0, 0, 0)
        user32.keybd_event(VK_MEDIA_NEXT_TRACK, 0, 2, 0)
        return "⏭️ Включен следующий трек"
    elif act in ("prev", "previous", "предыдущий", "назад"):
        user32.keybd_event(VK_MEDIA_PREV_TRACK, 0, 0, 0)
        user32.keybd_event(VK_MEDIA_PREV_TRACK, 0, 2, 0)
        return "⏮️ Включен предыдущий трек"
    elif act in ("stop", "стоп"):
        user32.keybd_event(VK_MEDIA_STOP, 0, 0, 0)
        user32.keybd_event(VK_MEDIA_STOP, 0, 2, 0)
        return "⏹️ Воспроизведение остановлено"
    return f"⚠️ Неизвестное медиа-действие: {action}"

def window_control(action: str = "minimize_all") -> str:
    """Управляет активными окнами рабочего стола Windows.
    Args:
        action: 'minimize_all' (свернуть все окна на рабочий стол), 'maximize' (развернуть окно на весь экран), 'minimize' (свернуть текущее окно), 'close' (закрыть текущее активное окно).
    """
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    act = action.lower().strip()
    if act in ("minimize_all", "desktop", "свернуть все", "рабочий стол"):
        _send_key_combo(VK_LWIN, 0x44)  # Win + D
        return "🖥️ Все окна свернуты (Рабочий стол открыт)"
    elif act in ("maximize", "развернуть", "на весь экран"):
        _send_key_combo(VK_LWIN, VK_UP)  # Win + Up
        return "🗖 Текущее окно развернуто на весь экран"
    elif act in ("minimize", "свернуть"):
        _send_key_combo(VK_LWIN, VK_DOWN)  # Win + Down
        return "🗕 Текущее окно свернуто"
    elif act in ("close", "закрой", "закрыть"):
        _send_key_combo(VK_MENU, VK_F4)  # Alt + F4
        return "✕ Активное окно закрыто"
    return f"⚠️ Неизвестное действие с окном: {action}"

def switch_window(title_keyword: str) -> str:
    """Находит открытое окно по названию приложения и переключается на него на передний план.
    Args:
        title_keyword: Ключевое слово в названии окна (например: 'Telegram', 'Chrome', 'Notepad', 'Visual Studio').
    """
    if sys.platform != "win32":
        return "⚠️ Доступно только на Windows"

    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    target_clean = title_keyword.lower().strip()
    found_hwnd = None
    found_title = ""

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def enum_windows_callback(hwnd, lparam):
        nonlocal found_hwnd, found_title
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if target_clean in title.lower():
                    found_hwnd = hwnd
                    found_title = title
                    return False
        return True

    user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

    if found_hwnd:
        user32.ShowWindow(found_hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(found_hwnd)
        return f"🪟 Переключился на окно: '{found_title}'"
    return f"⚠️ Окно с названием '{title_keyword}' не найдено среди запущенных программ."
