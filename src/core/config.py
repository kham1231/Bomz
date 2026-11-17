import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

def _parse_keys():
    keys = []
    # Collect from GEMINI_API_KEY and GEMINI_API_KEYS
    raw_sources = [
        os.getenv("GEMINI_API_KEY", ""),
        os.getenv("GEMINI_API_KEYS", "")
    ]
    for raw in raw_sources:
        if not raw:
            continue
        # Split by comma or semicolon
        for part in raw.replace(";", ",").split(","):
            cleaned = part.strip().strip("'\"")
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
    return keys

DEFAULT_CONFIG = {
    "api_keys": _parse_keys(),
    "active_key_index": 0,
    "active_model": "gemini-3.5-flash-lite",
    "secondary_model": "gemini-4-hydrogen",
    "available_models": [
        "gemini-3.5-flash-lite",
        "gemini-4-hydrogen"
    ],
    "wake_word": os.getenv("WAKE_WORD", "бомж").lower(),
    "wake_word_enabled": True,
    "hotkey": os.getenv("HOTKEY", "ctrl+shift+space"),
    "window_width": 440,
    "window_max_height": 650,
    "saved_x": None,
    "saved_y": None,
    "pin_window": False,
    "tts_enabled": False,
    "tts_speaker": "aidar",
    "available_speakers": ["aidar", "xenia", "baya", "kseniya", "eugene"],
    "autostart": False,
    "system_instruction": (
        "Ты — сообразительный, полезный и лаконичный десктопный ассистент по имени Бомж на компьютере пользователя под управлением Windows. "
        "Пользователя зовут Хамид, обращайся к нему с уважением.\n"
        "В твоем распоряжении есть мощный набор инструментов:\n"
        "- run_terminal_command: консоль PowerShell для работы с файлами, процессами, системой.\n"
        "- take_screenshot: снимок экрана и визуальный анализ открытых окон или ошибок.\n"
        "- change_volume: регулировка громкости (up/down/mute/unmute, либо точный процент level=0..100).\n"
        "- media_control: управление медиа (play_pause, next, prev, stop).\n"
        "- window_control: управление окнами (minimize_all, maximize, minimize, close).\n"
        "- switch_window: переключение на окно по названию приложения.\n"
        "- get_clipboard_text, set_clipboard_text: буфер обмена Windows.\n"
        "- search_web: поиск свежей информации и новостей в интернете.\n"
        "- uia_inspect_window: инспекция элементов интерфейса Windows (кнопки, поля ввода, списки).\n"
        "- uia_click: прямое нажатие на UI-элемент через Windows UI Automation.\n"
        "- uia_set_text: ввод текста в поле приложения через UI Automation.\n"
        "- browser_open_url: открытие ссылки в браузере (Chrome, Edge, Yandex, Brave).\n"
        "- browser_navigate, browser_click, browser_type, browser_get_content: автоматизация браузера через CDP / Playwright.\n"
        "- mouse_click, mouse_move, mouse_drag, type_text: клики по координатам экрана и ввод.\n"
        "Отвечай емко, структурированно, без лишней 'воды' и форматируй важное в Markdown."
    )
}

class ConfigManager:
    """Manages application settings, combining .env and config.json with multi-key round-robin support."""
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load()

    def get_valid_api_keys(self) -> list[str]:
        raw_keys = self.config.get("api_keys", [])
        clean_keys = []
        for item in raw_keys:
            if not isinstance(item, str):
                continue
            for part in item.replace(";", ",").split(","):
                k = part.strip().strip("'\"")
                if k and k not in clean_keys:
                    clean_keys.append(k)
        return clean_keys

    def load(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    if "available_models" in user_config:
                        user_config["available_models"] = [
                            m for m in user_config["available_models"]
                            if "2.5" not in m
                        ]
                        if not user_config["available_models"]:
                            user_config["available_models"] = [
                                "gemini-3.5-flash-lite",
                                "gemini-4-hydrogen"
                            ]

                    active = user_config.get("active_model", "")
                    if "2.5" in active or active not in user_config.get("available_models", []):
                        user_config["active_model"] = "gemini-3.5-flash-lite"

                    self.config.update(user_config)
            except Exception as e:
                logger.error(f"[Config] Error reading config.json: {e}")

        # Clean and flatten keys
        keys = self.get_valid_api_keys()
        for env_k in _parse_keys():
            if env_k not in keys:
                keys.append(env_k)

        self.config["api_keys"] = keys
        if "active_key_index" not in self.config or not isinstance(self.config["active_key_index"], int):
            self.config["active_key_index"] = 0

    def save(self):
        try:
            self.config["api_keys"] = self.get_valid_api_keys()
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[Config] Error saving config.json: {e}")

    def get(self, key, default=None):
        if key == "api_key":
            return self.get_active_api_key()
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()

    def get_active_api_key(self) -> str:
        keys = self.get_valid_api_keys()
        if not keys:
            return ""
        idx = self.config.get("active_key_index", 0) % len(keys)
        return keys[idx]

    def get_and_rotate_api_key(self) -> str:
        """
        Returns active API key and advances index to next key for the subsequent request (Round-Robin).
        """
        keys = self.get_valid_api_keys()
        if not keys:
            return ""
        if len(keys) == 1:
            return keys[0]

        curr_idx = self.config.get("active_key_index", 0) % len(keys)
        active_key = keys[curr_idx]
        next_idx = (curr_idx + 1) % len(keys)
        self.config["active_key_index"] = next_idx
        self.save()
        logger.info(f"[Config] Round-Robin API Key selected: #{curr_idx + 1} (...{active_key[-6:]}), next: #{next_idx + 1}")
        return active_key

    def rotate_api_key(self) -> str:
        keys = self.get_valid_api_keys()
        if len(keys) <= 1:
            return self.get_active_api_key()
        curr_idx = self.config.get("active_key_index", 0) % len(keys)
        next_idx = (curr_idx + 1) % len(keys)
        self.set("active_key_index", next_idx)
        new_key = keys[next_idx]
        logger.info(f"[Config] Rotated API Key to #{next_idx + 1} (ends in ...{new_key[-6:]})")
        return new_key

    def add_api_key(self, new_key: str):
        new_key = new_key.strip()
        if not new_key:
            return
        keys = self.get_valid_api_keys()
        if new_key not in keys:
            keys.append(new_key)
            self.set("api_keys", keys)

    def toggle_model(self):
        models = self.get("available_models", ["gemini-3.5-flash-lite", "gemini-4-hydrogen"])
        current = self.get("active_model")
        try:
            curr_idx = models.index(current)
            next_idx = (curr_idx + 1) % len(models)
            new_model = models[next_idx]
        except ValueError:
            new_model = models[0]
        self.set("active_model", new_model)
        return new_model

config = ConfigManager()
config.save()
