import os
import sys
import re
import difflib
import subprocess
import logging
from typing import Optional, Tuple, List, Dict
from src.tools.desktop import change_volume, media_control, window_control

logger = logging.getLogger(__name__)

# Fast mapping of common Russian phrases to Windows applications/protocols
FAST_APP_TARGETS = [
    (["настройк", "параметр", "settings"], "ms-settings:"),
    (["калькулятор", "calc"], "calc.exe"),
    (["блокнот", "notepad"], "notepad.exe"),
    (["диспетчер задач", "taskmgr", "процессы"], "taskmgr.exe"),
    (["проводник", "мой компьютер", "этот компьютер", "диск c", "файлы"], "explorer.exe"),
    (["браузер", "browser", "хром", "chrome", "яндекс"], "https://www.google.com"),
    (["терминал", "консоль", "powershell", "командную строку"], "wt.exe"),
]

# Process names for closing applications
APP_CLOSE_TARGETS: Dict[str, List[str]] = {
    "settings": ["SystemSettings.exe"],
    "calc": ["CalculatorApp.exe", "Calculator.exe", "calc.exe"],
    "notepad": ["notepad.exe"],
    "taskmgr": ["Taskmgr.exe"],
    "chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "yandex": ["browser.exe"],
    "firefox": ["firefox.exe"],
    "browser": ["chrome.exe", "msedge.exe", "browser.exe", "firefox.exe"],
    "telegram": ["Telegram.exe"],
    "discord": ["Discord.exe"],
    "steam": ["steam.exe"],
    "terminal": ["wt.exe", "powershell.exe", "cmd.exe"]
}

def _spawn_detached(cmd_str: str):
    """Spawns a detached process cleanly without ResourceWarning on Windows."""
    try:
        flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0
        p = subprocess.Popen(cmd_str, shell=True, creationflags=flags, close_fds=True)
        try:
            p.poll()
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"[FastLauncher] Spawn detached failed for '{cmd_str}': {e}")

class SemanticIntentEngine:
    """
    Ultra-fast (<2ms) local hardware semantic intent router.
    Extracts semantic meaning from natural Russian & English user speech
    using token stems, synonym rings, and fuzzy matching without invoking Gemini API.
    """
    # Action stems
    STEMS_VOL_UP = ("громч", "прибав", "навал", "подним", "увелич", "погромч")
    STEMS_VOL_DOWN = ("тиш", "убав", "приглуш", "уменьш", "сбав", "потиш", "прикрут")
    STEMS_VOL_MUTE = ("мьют", "заглуш", "беззвуч", "выруби звук", "выключи звук", "убери звук", "без звука")
    STEMS_VOL_UNMUTE = ("размьют", "включи звук", "верни звук", "разглуш")

    STEMS_MEDIA_PAUSE = ("пауз", "стоп", "плей", "останов", "воспроизвед", "продолж")
    STEMS_MEDIA_NEXT = ("следующ", "след", "дальш", "вперед", "скип", "переключ")
    STEMS_MEDIA_PREV = ("предыдущ", "прошл", "назад")

    STEMS_WIN_MIN_ALL = ("сверн", "спряч", "скрой", "убер", "сверни все")
    STEMS_WIN_MAX = ("разверн", "на весь экран", "полный экран")

    STEMS_OPEN = ("откр", "запуст", "вруб", "подруб", "стартон", "включ", "покаж", "запуск", "launch", "open", "start", "run")
    STEMS_CLOSE = ("закр", "выруб", "убей", "погас", "прибей", "выключ", "приконч", "kill", "close", "quit", "exit")

    # Target entity definitions: (canonical_name, synonyms/stems, launch_target, close_key)
    APP_DEFINITIONS = [
        ("настройки", ["настройк", "параметр", "settings"], "ms-settings:", "settings"),
        ("калькулятор", ["калькулятор", "кальк", "калькуляторе", "calc"], "calc.exe", "calc"),
        ("блокнот", ["блокнот", "блокнотик", "заметк", "текстовик", "notepad"], "notepad.exe", "notepad"),
        ("диспетчер задач", ["диспетчер задач", "диспетчер", "taskmgr", "процессы"], "taskmgr.exe", "taskmgr"),
        ("проводник", ["проводник", "мой компьютер", "этот компьютер", "диск c", "диск d", "файлы", "папк", "explorer"], "explorer.exe", "explorer"),
        ("хром", ["хром", "chrome"], "chrome", "chrome"),
        ("эдж", ["эдж", "edge"], "msedge", "edge"),
        ("яндекс браузер", ["яндекс", "yandex"], "browser", "yandex"),
        ("браузер", ["браузер", "браузерк", "браузерку", "browser"], "https://www.google.com", "browser"),
        ("телеграм", ["телеграм", "телег", "телегу", "тг", "telegram"], "telegram:", "telegram"),
        ("дискорд", ["дискорд", "диск", "дс", "discord"], "discord:", "discord"),
        ("стим", ["стим", "steam"], "steam:", "steam"),
        ("терминал", ["терминал", "консоль", "powershell", "командную строку", "командная строка", "cmd", "wt"], "wt.exe", "terminal"),
    ]

    VOL_TARGETS = ("звук", "громкост", "музык", "музл", "динамик", "саунд", "колонк")
    MEDIA_TARGETS = ("музык", "трек", "песн", "музл", "плеер", "видос", "видео")

    QUESTION_WORDS = ("как", "что", "почему", "зачем", "сколько", "где", "кто", "когда", "расскажи", "объясни", "напиши")

    RU_NUMBERS = {
        "ноль": 0, "нуль": 0, "один": 1, "два": 2, "три": 3, "четыре": 4, "пять": 5,
        "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
        "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
        "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
        "девятнадцать": 19, "двадцать": 20, "тридцать": 30, "сорок": 40,
        "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80,
        "девяносто": 90, "сто": 100
    }

    STEMS_ABORT = ("стоп", "остановись", "останови", "прекрати", "хватит", "отмена", "замолчи", "тихо", "молчи", "stop", "abort", "cancel")

    @classmethod
    def _is_abort_command(cls, text: str) -> bool:
        """Detects immediate user stop/abort instructions."""
        t = text.lower().strip()
        words = re.findall(r'[a-zA-Zа-яА-ЯёЁ]+', t)
        if not words:
            return False
        if len(words) <= 3 and any(w in cls.STEMS_ABORT or any(w.startswith(s) for s in cls.STEMS_ABORT) for w in words):
            return True
        return False

    # Sequence / purpose conjunction patterns identifying composite instructions
    COMPOSITE_CONJUNCTIONS = (
        r"\bи\s+\S+",
        r"\bзатем\b",
        r"\bпотом\b",
        r"\bпосле\s+чего\b",
        r"\bпосле\s+этого\b",
        r"\bчтобы\b",
        r"\bчтоб\b",
        r"\bдля\s+того\s+чтобы\b",
        r"\bа\s+затем\b",
        r"\bа\s+потом\b",
        r"\bа\s+также\b",
        r"\bдалее\b",
        r"\bтуда\b",
        r"\bтам\b",
    )

    # Secondary action stems indicating tool automation (UI Automation, Computer Use, Web Search)
    COMPOSITE_ACTION_STEMS = (
        "потыка", "потыч", "тыка", "ткни",
        "нажм", "нажат", "кликн", "щелкн", "клацн", "тапн",
        "посчита", "сосчита", "вычисл", "счита", "счит",
        "найд", "поищ", "погугл", "загугл", "ищи", "ищ",
        "введ", "ввест", "напечата", "напиш", "набер", "набрат", "впечата", "вбивай", "вбей",
        "пиш", "впиш", "спис", "допиш", "печат",
        "посмотр", "глян", "провер", "прочита", "просканиру", "узнай", "смотр",
        "скопиру", "встав",
    )

    @classmethod
    def _is_composite(cls, text: str) -> bool:
        """
        Determines if the command is a composite/multi-step instruction
        containing conjunctions ('и', 'затем', 'потом', 'после чего', 'чтобы')
        or secondary action verbs ('потыкай', 'нажми', 'посчитай', 'найди', 'введи', 'посмотри').
        Composite commands must NOT be intercepted by the fast router and must be
        dispatched to Gemini with its full suite of tools (UIA, Computer Use, Web Search).
        """
        t = text.lower()
        # 1. Check sequence / purpose conjunctions
        for pattern in cls.COMPOSITE_CONJUNCTIONS:
            if re.search(pattern, t):
                return True

        # 2. Check secondary action stems
        words = re.findall(r'[a-zA-Zа-яА-ЯёЁ]+', t)
        for w in words:
            for stem in cls.COMPOSITE_ACTION_STEMS:
                if w.startswith(stem) or stem in w:
                    return True

        # 3. Check for multiple distinct intents (e.g. app + volume, or multiple apps)
        matched_apps = sum(
            1 for name, synonyms, _, _ in cls.APP_DEFINITIONS
            if any(syn in t or any(w.startswith(syn) for w in words) for syn in synonyms)
        )
        has_vol = any(any(w.startswith(vt) for vt in cls.VOL_TARGETS) for w in words)
        if matched_apps > 1 or (matched_apps >= 1 and has_vol):
            return True

        # 4. Trailing Instruction Rule:
        # If there are 2 or more meaningful words after the target app, it is a multi-step instruction
        # (e.g. "открой браузер из пиши туда как сделать чучело").
        for name, synonyms, _, _ in cls.APP_DEFINITIONS:
            for syn in synonyms:
                pattern = rf"\b{re.escape(syn)}\b\s+(.+)$"
                match = re.search(pattern, t)
                if match:
                    trailing_text = match.group(1).strip()
                    trailing_words = re.findall(r'[a-zA-Zа-яА-ЯёЁ]+', trailing_text)
                    meaningful = [w for w in trailing_words if w not in ("пожалуйста", "быстро", "мне", "плиз", "щас", "сейчас")]
                    if len(meaningful) >= 2:
                        return True

        return False

    @classmethod
    def _is_question(cls, text: str) -> bool:
        """Determines if the text is asking an open-ended informational question."""
        tokens = text.lower().split()
        if not tokens:
            return False
        # If it starts with question words and has no explicit command verb
        if tokens[0] in cls.QUESTION_WORDS:
            return True
        if "?" in text and len(tokens) > 3 and not any(v in text for v in ("звук", "громкость", "окно", "пауза")):
            return True
        return False

    @classmethod
    def _match_stem(cls, word: str, stems: tuple) -> bool:
        return any(word.startswith(stem) or stem in word for stem in stems)

    @classmethod
    def _extract_volume_level(cls, q: str) -> Optional[int]:
        # 1. Exact numeric digits (e.g. "звук 50", "громкость 25%", "поставь звук на 70")
        vol_match = re.search(r'(?:поставь|сделай|установи|сбавь|накрути)?\s*(?:звук|громкость)\s*(?:на)?\s*(\d{1,3})\s*%?', q)
        if not vol_match:
            vol_match = re.search(r'(\d{1,3})\s*%\s*(?:громкост[ьи]|звук[ае]?)', q)
        if not vol_match:
            vol_match = re.search(r'(?:звук|громкость)\s+(\d{1,3})\b', q)
        if vol_match:
            val = int(vol_match.group(1))
            if 0 <= val <= 100:
                return val

        # 2. Spoken Russian word-numbers from speech recognition (e.g. "звук пятьдесят", "громкость на двадцать процентов")
        tokens = re.findall(r'[a-zA-Zа-яА-ЯёЁ]+', q)
        has_vol = any(t.startswith("звук") or t.startswith("громкост") for t in tokens)
        if has_vol:
            words_num = [cls.RU_NUMBERS[w] for w in tokens if w in cls.RU_NUMBERS]
            if len(words_num) == 1:
                return words_num[0]
            elif len(words_num) == 2 and words_num[0] in (20, 30, 40, 50, 60, 70, 80, 90) and 1 <= words_num[1] <= 9:
                return words_num[0] + words_num[1]
        return None

    @classmethod
    def parse_and_execute(cls, query: str) -> Optional[str]:
        q = query.lower().strip()
        # Clean wake word prefixes from the query if present
        q = re.sub(r"^(?:(?:слушай|привет|эй|хей|ок|окей)\s+)?(?:бомж\w*|бонж\w*|компьютер\w*|ассистент\w*)[\s,]*", "", q).strip()
        if not q:
            return None

        # 0. Immediate Stop / Abort Intent
        if cls._is_abort_command(q):
            logger.info(f"[SemanticEngine] Abort command matched: '{q}'")
            return "[STOP]"

        # Do not intercept informational or coding questions
        if cls._is_question(q):
            return None

        # Do not intercept composite/multi-step commands (require Gemini agent tool chaining)
        if cls._is_composite(q):
            logger.info(f"[SemanticEngine] Query is composite, passing through to Gemini: '{q}'")
            return None

        # 1. Exact volume percentage matching (digits or Russian number words)
        val = cls._extract_volume_level(q)
        if val is not None:
            logger.info(f"[SemanticEngine] Exact volume match: {val}%")
            return change_volume(action="set", level=val)

        # 1b. Maximum / Minimum volume shortcuts
        if any(kw in q for kw in ["звук на максимум", "громкость на максимум", "звук на полную", "звук на всю", "громкость на всю", "навали на полную"]):
            return change_volume(action="set", level=100)
        if any(kw in q for kw in ["звук на минимум", "громкость на минимум", "звук в ноль", "звук на ноль", "громкость в ноль", "убавь в ноль"]):
            return change_volume(action="set", level=0)

        # 2. Volume control (Mute / Unmute / Up / Down)
        if any(kw in q for kw in ["без звука", "выключи звук", "заглуши", "мьют", "выруби звук", "заглуши звук"]):
            return change_volume("mute")
        if any(kw in q for kw in ["включи звук", "размьють", "верни звук", "разглуши"]):
            return change_volume("unmute")

        words = re.findall(r'[a-zA-Zа-яА-ЯёЁ0-9]+', q)

        has_vol_target = any(any(w.startswith(vt) for vt in cls.VOL_TARGETS) for w in words)
        has_vol_up = any(any(w.startswith(stem) for stem in cls.STEMS_VOL_UP) for w in words)
        has_vol_down = any(any(w.startswith(stem) for stem in cls.STEMS_VOL_DOWN) for w in words)

        if has_vol_up and (has_vol_target or "погромче" in q or "громче" in q or "навали" in q):
            return change_volume("up")
        if has_vol_down and (has_vol_target or "потише" in q or "тише" in q or "приглуши" in q):
            return change_volume("down")

        # 3. Media control
        if any(kw in q for kw in ["следующий трек", "следующая песня", "переключи трек", "след трек", "дальше трек", "скипни трек", "следующую"]):
            return media_control("next")
        if any(kw in q for kw in ["предыдущий трек", "предыдущая песня", "прошлый трек", "предыдущую"]):
            return media_control("prev")

        has_media_target = any(any(w.startswith(mt) for mt in cls.MEDIA_TARGETS) for w in words)
        has_pause = any(any(w.startswith(stem) for stem in cls.STEMS_MEDIA_PAUSE) for w in words)
        if has_pause and (has_media_target or any(kw in q for kw in ["пауза", "паузу", "плей", "продолжи", "останови музыку", "выключи музыку", "поставь на паузу"])):
            return media_control("play_pause")

        # 4. Window control
        if any(kw in q for kw in ["сверни все окна", "сверни окна", "покажи рабочий стол", "на рабочий стол", "спрячь все окна", "спрячь окна", "скрой окна", "скрой все окна", "сверни все", "сверни всё"]):
            return window_control("minimize_all")
        if any(kw in q for kw in ["разверни окно", "на весь экран", "полный экран"]):
            return window_control("maximize")
        if any(kw in q for kw in ["закрой окно", "закрой это окно", "закрой текущее окно"]):
            return window_control("close")
        if any(kw in q for kw in ["сверни окно", "сверни это окно", "сверни текущее окно"]):
            return window_control("minimize")

        # 5. App Close Intent
        has_close_verb = any(any(w.startswith(stem) for stem in cls.STEMS_CLOSE) for w in words)
        if has_close_verb:
            for name, synonyms, launch_tgt, close_key in cls.APP_DEFINITIONS:
                matched_app = False
                for syn in synonyms:
                    if syn in q or any(w.startswith(syn) for w in words):
                        matched_app = True
                        break
                if matched_app:
                    if close_key == "explorer":
                        return window_control("close")
                    procs = APP_CLOSE_TARGETS.get(close_key, [])
                    if procs:
                        logger.info(f"[SemanticEngine] Closing app '{name}' (processes: {procs})")
                        for proc in procs:
                            _spawn_detached(f'taskkill /IM "{proc}" /F')
                        return f"Закрываю {name}..."
                    else:
                        return window_control("close")

        # 6. App Launch Intent
        has_open_verb = any(any(w.startswith(stem) for stem in cls.STEMS_OPEN) for w in words)
        if has_open_verb or any(kw in q for kw in ["открой", "запусти", "включи", "покажи", "open", "launch", "start"]):
            for name, synonyms, launch_tgt, close_key in cls.APP_DEFINITIONS:
                matched_app = False
                for syn in synonyms:
                    if syn in q or any(w.startswith(syn) for w in words):
                        matched_app = True
                        break
                    # Fuzzy match check for typos e.g. 'калькулятор' vs 'калькулатор'
                    for w in words:
                        if len(w) >= 4 and len(syn) >= 4:
                            ratio = difflib.SequenceMatcher(None, w, syn).ratio()
                            if ratio >= 0.82:
                                matched_app = True
                                break
                    if matched_app:
                        break

                if matched_app:
                    try:
                        logger.info(f"[SemanticEngine] Matched app launch '{name}' -> target: {launch_tgt}")
                        if launch_tgt.startswith("http://") or launch_tgt.startswith("https://") or launch_tgt.endswith(":"):
                            os.startfile(launch_tgt)
                        else:
                            _spawn_detached(f'start "" "{launch_tgt}"')
                        return f"Открываю {name}..."
                    except Exception as e:
                        logger.warning(f"[SemanticEngine] Error launching {launch_tgt}: {e}")
                        try:
                            _spawn_detached(f'start {launch_tgt}')
                            return f"Открываю {name}..."
                        except Exception as e2:
                            logger.error(f"[SemanticEngine] Fallback failed for {launch_tgt}: {e2}")
                            return None

        return None

def try_fast_launch(query: str) -> Optional[str]:
    """
    Checks if a user query is a simple 'open app' request or desktop control shortcut.
    If matched, executes directly in ~2-5ms via SemanticIntentEngine.
    Returns a human-readable confirmation string, or None if no match.
    """
    if sys.platform != "win32":
        return None

    return SemanticIntentEngine.parse_and_execute(query)

def execute_fast_command(command: str) -> Optional[str]:
    """
    Checks if a terminal command can be executed directly via Windows Shell (5ms)
    instead of launching a full PowerShell process (800ms+).
    """
    if sys.platform != "win32":
        return None

    cmd = command.strip()
    cmd_lower = cmd.lower()

    # Match commands like 'start ms-settings:...', 'start notepad', 'explorer.exe'
    if cmd_lower.startswith("start "):
        target = cmd[6:].strip()
        try:
            logger.info(f"[FastLauncher] Fast-executing start command: {target}")
            if target.startswith("http") or target.endswith(":") or target.startswith("ms-"):
                os.startfile(target)
            else:
                _spawn_detached(f'start "" {target}')
            return f"[Приложение '{target}' успешно запущено мгновенно]"
        except Exception as e:
            logger.warning(f"[FastLauncher] Fast launch error for '{target}': {e}")
            return None

    elif cmd_lower in ("calc", "calc.exe", "notepad", "notepad.exe", "taskmgr", "taskmgr.exe", "explorer", "explorer.exe"):
        try:
            logger.info(f"[FastLauncher] Fast-executing app: {cmd}")
            _spawn_detached(f'start "" "{cmd}"')
            return f"[Приложение '{cmd}' успешно запущено мгновенно]"
        except Exception as e:
            logger.warning(f"[FastLauncher] Fast launch error for '{cmd}': {e}")
            return None

    return None
