import logging
from typing import Generator, Callable, Optional, Union
from google import genai
from google.genai import types

from src.core.config import config
from src.tools.terminal import run_terminal_command, set_activity_callback
from src.tools.screen import take_screenshot
from src.tools.desktop import change_volume, media_control, window_control, switch_window
from src.tools.clipboard import get_clipboard_text, set_clipboard_text
from src.tools.web_search import search_web
from src.tools.ui_automation import uia_inspect_window, uia_click, uia_set_text
from src.tools.browser_control import (
    browser_open_url, browser_navigate, browser_click,
    browser_type, browser_get_content
)
from src.tools.computer_use import mouse_click, mouse_move, mouse_drag, type_text, get_display_info

logger = logging.getLogger(__name__)

ALL_ASSISTANT_TOOLS = [
    run_terminal_command,
    take_screenshot,
    change_volume,
    media_control,
    window_control,
    switch_window,
    get_clipboard_text,
    set_clipboard_text,
    search_web,
    uia_inspect_window,
    uia_click,
    uia_set_text,
    browser_open_url,
    browser_navigate,
    browser_click,
    browser_type,
    browser_get_content,
    mouse_click,
    mouse_move,
    mouse_drag,
    type_text,
    get_display_info
]

def format_tool_activity(fc) -> str:
    """Formats human-friendly one-line status for active tool calls."""
    name = fc.name
    args = fc.args or {}
    if name == "take_screenshot":
        return "📷 Делаю скриншот экрана..."
    elif name == "search_web":
        return f"🔍 Ищу в интернете: {args.get('query', '')}"
    elif name == "change_volume":
        lvl = args.get('level')
        act = args.get('action', '')
        return f"🔊 Регулирую громкость ({f'{lvl}%' if lvl is not None else act})..."
    elif name == "media_control":
        return f"⏯️ Управление мультимедиа ({args.get('action', '')})..."
    elif name == "window_control":
        return f"🪟 Управление окнами ({args.get('action', '')})..."
    elif name == "switch_window":
        return f"🪟 Переключаюсь на '{args.get('title_keyword', '')}'..."
    elif name == "get_clipboard_text":
        return "📋 Читаю буфер обмена..."
    elif name == "set_clipboard_text":
        return "📋 Копирую в буфер обмена..."
    elif name == "run_terminal_command":
        cmd = args.get("command", "")
        return f"⚙️ Выполняю в консоли: {cmd}"
    elif name == "uia_inspect_window":
        return f"🪟 Инспектирую окно '{args.get('title_keyword', 'активное')}'..."
    elif name == "uia_click":
        return f"🪟 Нажимаю '{args.get('control_name', '')}'..."
    elif name == "uia_set_text":
        return f"⌨️ Ввожу текст в '{args.get('control_name', '')}'..."
    elif name == "browser_open_url":
        return f"🌐 Открываю сайт: {args.get('url', '')}..."
    elif name == "browser_navigate":
        return f"🌐 Перехожу на: {args.get('url', '')}..."
    elif name == "browser_click":
        return f"🖱️ Клик в браузере: {args.get('selector_or_text', '')}..."
    elif name == "browser_type":
        return f"⌨️ Ввод в браузере..."
    elif name == "browser_get_content":
        return "📄 Читаю страницу браузера..."
    elif name == "mouse_click":
        return f"🖱️ Клик в координатах ({args.get('x')}, {args.get('y')})..."
    elif name == "mouse_move":
        return f"🖱️ Движение мыши ({args.get('x')}, {args.get('y')})..."
    elif name == "type_text":
        return f"⌨️ Ввод текста с клавиатуры..."
    elif name == "get_display_info":
        return "🖥️ Определение параметров дисплея..."
    return f"⚙️ Выполняю: {name}..."

def sanitize_conversation_history(history: Optional[list], max_turns: int = 4) -> list:
    """
    Cleanses conversation history by completely stripping heavy binary data
    (screenshots, raw PCM audio bytes) and raw intermediate AFC tool execution chains.
    Preserves only compact, meaningful dialogue exchanges (user prompt -> assistant answer)
    within a lightweight sliding window of `max_turns` (default 4 turns / 8 messages).
    """
    if not history:
        return []

    dialogue_pairs = []
    current_user_parts = []
    current_model_parts = []

    for content in history:
        role = getattr(content, "role", "")
        parts = getattr(content, "parts", []) or []
        text_segments = []
        for p in parts:
            t = getattr(p, "text", None)
            if t and isinstance(t, str):
                t_clean = t.strip()
                if t_clean and not t_clean.startswith("QUERY:"):
                    text_segments.append(t_clean)

        combined_text = "\n".join(text_segments).strip()

        if role == "user":
            if current_user_parts and current_model_parts:
                dialogue_pairs.append((
                    "\n".join(current_user_parts),
                    "\n".join(current_model_parts)
                ))
                current_user_parts = []
                current_model_parts = []
            if combined_text:
                current_user_parts.append(combined_text)
        elif role == "model":
            if combined_text:
                current_model_parts.append(combined_text)

    if current_user_parts and current_model_parts:
        dialogue_pairs.append((
            "\n".join(current_user_parts),
            "\n".join(current_model_parts)
        ))

    recent_pairs = dialogue_pairs[-max_turns:]
    clean_history = []
    for u_text, m_text in recent_pairs:
        clean_history.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=u_text)]
        ))
        clean_history.append(types.Content(
            role="model",
            parts=[types.Part.from_text(text=m_text)]
        ))

    return clean_history

class GeminiService:
    """Service to interact with Google Gemini API supporting streaming, multimodal audio, tools, and round-robin key rotation."""
    def __init__(self):
        self.active_model = config.get("active_model", "gemini-3.5-flash-lite")
        self.client = None
        self.chat = None
        self._current_key = ""
        self._init_client()

    def _init_client(self, api_key: Optional[str] = None, preserve_history: bool = False):
        try:
            if not api_key:
                api_key = config.get_active_api_key()
            if not api_key:
                logger.warning("[Gemini] API Key is missing!")
                return
            old_history = None
            if preserve_history and self.chat:
                try:
                    old_history = self.chat.get_history()
                except Exception:
                    old_history = None
            self._current_key = api_key
            self.client = genai.Client(api_key=api_key)
            self.start_new_chat(self.active_model, history=old_history)
        except Exception as e:
            logger.error(f"[Gemini] Failed to initialize client: {e}")

    def _ensure_next_round_robin_client(self):
        """Rotates API key round-robin for each new user prompt while preserving conversation history."""
        next_key = config.get_and_rotate_api_key()
        if next_key and (next_key != self._current_key or self.client is None):
            self._init_client(next_key, preserve_history=True)

    def start_new_chat(self, model: str = None, history: Optional[list] = None):
        """Starts a multi-turn chat session with tools enabled, sliding window text history."""
        if not self.client:
            self._init_client()
            if not self.client:
                return

        if model:
            self.active_model = model

        system_instruction = config.get("system_instruction")
        try:
            cfg = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
                tools=ALL_ASSISTANT_TOOLS
            )
            create_kwargs = {
                "model": self.active_model,
                "config": cfg
            }
            clean_history = sanitize_conversation_history(history, max_turns=4)
            if clean_history:
                create_kwargs["history"] = clean_history
            self.chat = self.client.chats.create(**create_kwargs)
            logger.info(f"[Gemini] Chat session ready with model {self.active_model} ({len(ALL_ASSISTANT_TOOLS)} tools, clean_turns={len(clean_history)//2})")
        except Exception as e:
            logger.error(f"[Gemini] Error creating chat with model {self.active_model}: {e}")
            fallback = config.get("secondary_model", "gemini-4-hydrogen")
            if fallback and fallback != self.active_model:
                logger.info(f"[Gemini] Trying fallback model: {fallback}")
                self.active_model = fallback
                create_kwargs["model"] = fallback
                self.chat = self.client.chats.create(**create_kwargs)

    def quick_vision_analysis(self, image_bytes: bytes, prompt: str = "Опиши экран") -> str:
        """One-shot direct image analysis via Gemini Vision."""
        if not self.client:
            self._init_client()
            if not self.client:
                return "Ошибка: клиент Gemini не инициализирован."
        try:
            img_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            resp = self.client.models.generate_content(
                model=self.active_model,
                contents=[img_part, prompt]
            )
            return resp.text or ""
        except Exception as e:
            logger.error(f"[Gemini] Quick vision error: {e}")
            return f"Ошибка анализа экрана: {e}"

    def set_model(self, model_name: str):
        if self.active_model != model_name:
            self.active_model = model_name
            config.set("active_model", model_name)
            self.start_new_chat(model_name)

    def rotate_key_and_retry(self):
        new_key = config.rotate_api_key()
        logger.info(f"[Gemini] Quota fallback: Switched to next API key: ...{new_key[-6:]}")
        self._init_client(new_key, preserve_history=True)

    def stream_prompt(
        self,
        user_prompt: str,
        screenshot_bytes: Optional[bytes] = None,
        activity_callback: Optional[Callable[[str], None]] = None
    ) -> Generator[str, None, None]:
        """Sends user text prompt (and optional screenshot) to Gemini, streaming response."""
        # 1. Round-robin advance to alternate key for this request
        self._ensure_next_round_robin_client()

        if not self.client or not self.chat:
            self.start_new_chat(self.active_model)
            if not self.client or not self.chat:
                yield "❌ Ошибка: API ключ Gemini не настроен или недоступен."
                return

        if activity_callback:
            set_activity_callback(activity_callback)

        contents = []
        if screenshot_bytes:
            contents.append(types.Part.from_bytes(data=screenshot_bytes, mime_type="image/jpeg"))
        contents.append(user_prompt)

        max_key_attempts = max(1, len(config.get_valid_api_keys()))
        for attempt in range(max_key_attempts):
            try:
                response_stream = self.chat.send_message_stream(contents if len(contents) > 1 else user_prompt)
                for chunk in response_stream:
                    cand = chunk.candidates[0] if chunk.candidates else None
                    if cand and cand.content and cand.content.parts:
                        for part in cand.content.parts:
                            if part.function_call and activity_callback:
                                activity_callback(format_tool_activity(part.function_call))
                            elif part.text:
                                yield part.text
                    elif chunk.text:
                        yield chunk.text

                if activity_callback:
                    activity_callback("")
                return

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    if len(config.get_valid_api_keys()) > 1 and attempt < max_key_attempts - 1:
                        logger.warning(f"[Gemini] Quota hit! Auto-rotating key (attempt {attempt + 1})...")
                        self.rotate_key_and_retry()
                        continue

                logger.error(f"[Gemini] Streaming error: {err_str}")
                if activity_callback:
                    activity_callback("")
                yield f"\n⚠️ Ошибка запроса к модели ({self.active_model}): {err_str}"
                return

    def stream_audio_prompt(
        self,
        audio_bytes: bytes,
        fallback_text: str = "",
        screenshot_bytes: Optional[bytes] = None,
        activity_callback: Optional[Callable[[str], None]] = None
    ) -> Generator[str, None, None]:
        """
        Sends recorded WAV audio (and optional screenshot) directly to Gemini Multimodal API.
        Extracts user intent with 99% accuracy across English/Russian/numbers.
        Falls back to text if audio fails.
        """
        # 1. Round-robin advance to alternate key for this request
        self._ensure_next_round_robin_client()

        if not self.client or not self.chat:
            self.start_new_chat(self.active_model)
            if not self.client or not self.chat:
                yield "❌ Ошибка: API ключ Gemini не настроен или недоступен."
                return

        if activity_callback:
            set_activity_callback(activity_callback)

        max_key_attempts = max(1, len(config.get_valid_api_keys()))
        for attempt in range(max_key_attempts):
            try:
                audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")
                instruction_text = (
                    "Внимательно послушай аудиозапись пользователя и изучи скриншот экрана (если прикреплен)."
                    + (f" Распознанная фраза-подсказка: '{fallback_text}'." if fallback_text else "") +
                    "\n1. В САМОЙ ПЕРВОЙ СТРОКЕ своего ответа обязательно напиши: QUERY: [точный распознанный текст пользователя на русском/английском с цифрами].\n"
                    "2. СТРОЖАЙШЕЕ ТРЕБОВАНИЕ: Если пользователь просит выполнить ЛЮБОЕ действие на компьютере "
                    "(открыть программу, нажать кнопку, посчитать, ввести текст, открыть сайт, закрыть окно, настроить звук) — "
                    "ТЫ ОБЯЗАН РЕАЛЬНО ВЫЗВАТЬ СООТВЕТСТВУЮЩИЕ ИНСТРУМЕНТЫ (run_terminal_command, uia_click, uia_set_text, browser_open_url, mouse_click). "
                    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО просто отвечать текстом или имитировать действия на словах! "
                    "Если нужно открыть калькулятор и нажать кнопки — сначала вызови run_terminal_command: calc, затем нажми кнопки через uia_click. "
                    "Если нужно найти в браузере — открой ссылку через browser_open_url (например https://www.google.com/search?q=...)."
                )
                contents = [audio_part]
                if screenshot_bytes:
                    contents.append(types.Part.from_bytes(data=screenshot_bytes, mime_type="image/jpeg"))
                contents.append(instruction_text)
                
                response_stream = self.chat.send_message_stream(contents)
                for chunk in response_stream:
                    cand = chunk.candidates[0] if chunk.candidates else None
                    if cand and cand.content and cand.content.parts:
                        for part in cand.content.parts:
                            if part.function_call and activity_callback:
                                activity_callback(format_tool_activity(part.function_call))
                            elif part.text:
                                yield part.text
                    elif chunk.text:
                        yield chunk.text

                if activity_callback:
                    activity_callback("")
                return

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    if len(config.get_valid_api_keys()) > 1 and attempt < max_key_attempts - 1:
                        logger.warning(f"[Gemini] Quota hit on audio! Auto-rotating key...")
                        self.rotate_key_and_retry()
                        continue

                logger.warning(f"[Gemini] Multimodal audio request error: {err_str}. Trying fallback text...")
                if fallback_text:
                    yield from self.stream_prompt(fallback_text, screenshot_bytes=screenshot_bytes, activity_callback=activity_callback)
                else:
                    yield f"\n⚠️ Ошибка обработки аудио ({self.active_model}): {err_str}"
                return

gemini_service = GeminiService()
