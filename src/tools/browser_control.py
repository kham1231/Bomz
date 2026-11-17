import os
import sys
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Common browser executable locations on Windows
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
YANDEX_PATHS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Yandex\YandexBrowser\Application\browser.exe"),
    r"C:\Program Files\Yandex\YandexBrowser\Application\browser.exe",
]
BRAVE_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
]
FIREFOX_PATHS = [
    r"C:\Program Files\Mozilla Firefox\firefox.exe",
    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"),
]

def _find_browser_executable() -> Optional[str]:
    all_candidates = CHROME_PATHS + EDGE_PATHS + YANDEX_PATHS + BRAVE_PATHS
    for p in all_candidates:
        if os.path.exists(p):
            return p
    return None

def _find_firefox_executable() -> Optional[str]:
    for p in FIREFOX_PATHS:
        if os.path.exists(p):
            return p
    return None

class BrowserManager:
    """Manages CDP / Playwright browser session with automatic fallback across browsers."""
    _instance = None

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = BrowserManager()
        return cls._instance

    def _ensure_page(self):
        if self._page and not self._page.is_closed():
            return self._page

        from playwright.sync_api import sync_playwright
        if self._playwright is None:
            self._playwright = sync_playwright().start()

        # 1. Try connecting to existing browser over CDP (e.g. localhost:9222)
        try:
            self._browser = self._playwright.chromium.connect_over_cdp("http://localhost:9222", timeout=1500)
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else self._browser.new_context()
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()
            logger.info("[BrowserControl] Connected to active browser via CDP on port 9222")
            return self._page
        except Exception:
            pass

        # 2. Launch browser with installed Chromium executable (Chrome, Edge, Yandex, Brave)
        exe = _find_browser_executable()
        launch_kwargs = {"headless": False}
        if exe:
            launch_kwargs["executable_path"] = exe

        try:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
            logger.info(f"[BrowserControl] Launched browser: {exe or 'Chromium default'}")
            return self._page
        except Exception as e:
            logger.warning(f"[BrowserControl] Chromium launch failed ({e}), checking Firefox...")
            ff_exe = _find_firefox_executable()
            ff_kwargs = {"headless": False}
            if ff_exe:
                ff_kwargs["executable_path"] = ff_exe
            try:
                self._browser = self._playwright.firefox.launch(**ff_kwargs)
                self._context = self._browser.new_context()
                self._page = self._context.new_page()
                logger.info(f"[BrowserControl] Launched Firefox: {ff_exe or 'Firefox default'}")
                return self._page
            except Exception as ff_e:
                logger.error(f"[BrowserControl] All browser launches failed: {ff_e}")
                raise e

    def close(self):
        try:
            if self._page:
                self._page.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._browser = None
        self._playwright = None

def browser_open_url(url: str) -> str:
    """Мгновенно открывает ссылку (URL) в браузере пользователя по умолчанию (~2мс).
    Args:
        url: Веб-адрес (например: 'https://youtube.com', 'https://github.com', 'google.com').
    """
    clean_url = url.strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = f"https://{clean_url}"

    try:
        if sys.platform == "win32":
            os.startfile(clean_url)
        else:
            import webbrowser
            webbrowser.open(clean_url)
        return f"🌐 Открыта ссылка: {clean_url}"
    except Exception as e:
        logger.error(f"[BrowserControl] Failed to open URL: {e}")
        return f"⚠️ Ошибка открытия ссылки: {e}"

def browser_navigate(url: str) -> str:
    """Переходит по указанному URL в автоматизированном браузере (CDP / Playwright).
    Args:
        url: Веб-адрес для перехода.
    """
    clean_url = url.strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = f"https://{clean_url}"

    try:
        mgr = BrowserManager.get_instance()
        page = mgr._ensure_page()
        page.goto(clean_url, timeout=12000)
        title = page.title()
        return f"🌐 Страница успешно загружена: «{title}» ({page.url})"
    except Exception as e:
        logger.error(f"[BrowserControl] Navigate error: {e}")
        return f"⚠️ Ошибка перехода на страницу '{url}': {e}"

def browser_click(selector_or_text: str) -> str:
    """Кликает по кнопке, ссылке или элементу на веб-странице по CSS-селектору или тексту.
    Args:
        selector_or_text: CSS-селектор (например: 'button.submit', '#login') или текст ('Войти', 'Search').
    """
    try:
        mgr = BrowserManager.get_instance()
        page = mgr._ensure_page()
        sel = selector_or_text.strip()
        # If selector doesn't look like CSS selector, try text selector
        if not any(ch in sel for ch in ["#", ".", "[", ">", ":"]):
            target = f"text={sel}"
        else:
            target = sel

        page.click(target, timeout=5000)
        return f"✅ Клик по элементу '{selector_or_text}' выполнен."
    except Exception as e:
        logger.error(f"[BrowserControl] Click error: {e}")
        return f"⚠️ Ошибка клика по элементу '{selector_or_text}': {e}"

def browser_type(selector: str, text: str, press_enter: bool = False) -> str:
    """Вводит текст в поле ввода на веб-странице.
    Args:
        selector: CSS-селектор поля (например: 'input[name=\"q\"]', '#search').
        text: Текст для ввода.
        press_enter: Нажать Enter после ввода текста (по умолчанию False).
    """
    try:
        mgr = BrowserManager.get_instance()
        page = mgr._ensure_page()
        page.fill(selector, text, timeout=5000)
        if press_enter:
            page.press(selector, "Enter")
        return f"✅ В поле '{selector}' введен текст: «{text}»"
    except Exception as e:
        logger.error(f"[BrowserControl] Type error: {e}")
        return f"⚠️ Ошибка ввода текста в '{selector}': {e}"

def browser_get_content(selector: Optional[str] = None, max_length: int = 1500) -> str:
    """Возвращает текстовое содержимое открытой страницы или выбранного блока.
    Args:
        selector: Необязательный CSS-селектор для чтения конкретного блока.
        max_length: Максимальное количество символов для вывода.
    """
    try:
        mgr = BrowserManager.get_instance()
        page = mgr._ensure_page()
        if selector:
            content = page.inner_text(selector, timeout=4000)
        else:
            content = page.inner_text("body", timeout=4000)

        cleaned = " ".join(content.split())
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length] + "...\n[текст обрезан]"
        return f"📄 Содержимое страницы «{page.title()}»:\n{cleaned}"
    except Exception as e:
        logger.error(f"[BrowserControl] Get content error: {e}")
        return f"⚠️ Ошибка чтения содержимого страницы: {e}"
