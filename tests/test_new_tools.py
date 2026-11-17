import unittest
import sys
from PyQt6.QtWidgets import QApplication

from src.tools.screen import has_screen_intent, capture_screen_bytes
from src.tools.desktop import change_volume, media_control, window_control
from src.tools.clipboard import get_clipboard_text, set_clipboard_text
from src.tools.web_search import search_web
from src.services.gemini_service import format_tool_activity

class TestNewTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def test_screen_intent_and_capture(self):
        self.assertTrue(has_screen_intent("Бомж, посмотри на экран"))
        self.assertTrue(has_screen_intent("что тут за ошибка?"))
        self.assertTrue(has_screen_intent("сделай скриншот"))
        self.assertFalse(has_screen_intent("какая погода в Париже?"))

        # Screen capture
        img_bytes = capture_screen_bytes(max_width=640)
        self.assertIsInstance(img_bytes, (bytes, bytearray))
        self.assertGreater(len(img_bytes), 0)

    def test_desktop_control(self):
        # Sound
        res_vol = change_volume("up")
        self.assertIn("Громкость", res_vol)
        res_mute = change_volume("mute")
        self.assertIn("звука", res_mute)

        # Media
        res_media = media_control("play_pause")
        self.assertIn("Пауза", res_media)

        # Window
        res_win = window_control("minimize_all")
        self.assertIn("Рабочий стол", res_win)

    def test_clipboard(self):
        test_str = "Тестовая строка для буфера обмена 12345"
        res_set = set_clipboard_text(test_str)
        self.assertIn("успешно", res_set)
        
        res_get = get_clipboard_text()
        self.assertIn(test_str, res_get)

    def test_web_search(self):
        res = search_web("python programming language", max_results=2)
        self.assertIsInstance(res, str)
        self.assertTrue("Результаты поиска" in res or "По запросу" in res)

    def test_format_tool_activity(self):
        class MockFC:
            def __init__(self, name, args=None):
                self.name = name
                self.args = args or {}

        fc_screen = MockFC("take_screenshot")
        self.assertIn("скриншот", format_tool_activity(fc_screen))

        fc_search = MockFC("search_web", {"query": "тест"})
        self.assertIn("тест", format_tool_activity(fc_search))

        fc_vol = MockFC("change_volume", {"action": "up"})
        self.assertIn("громкость", format_tool_activity(fc_vol))

if __name__ == "__main__":
    unittest.main()
