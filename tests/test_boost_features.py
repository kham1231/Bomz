import unittest
import sys
from PyQt6.QtWidgets import QApplication

from src.core.config import config
from src.core.autostart import is_autostart_enabled, set_autostart
from src.tools.desktop import change_volume, get_master_volume_percent, set_master_volume_percent
from src.tools.fast_launcher import try_fast_launch
from src.tools.web_search import search_web
from src.tools.ui_automation import uia_inspect_window
from src.tools.browser_control import browser_open_url
from src.tools.computer_use import get_display_info, mouse_move, mouse_click
from src.ui.mic_indicator import AnimatedMicIndicator
from src.ui.hud_window import HUDWindow

class TestBoostFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def test_api_keys_round_robin(self):
        keys = config.get_valid_api_keys()
        self.assertGreaterEqual(len(keys), 2)
        # Verify alternate round-robin cycling
        k1 = config.get_and_rotate_api_key()
        k2 = config.get_and_rotate_api_key()
        self.assertNotEqual(k1, k2)
        k3 = config.get_and_rotate_api_key()
        self.assertEqual(k1, k3)

    def test_volume_exact_percentage(self):
        orig_vol = get_master_volume_percent()
        try:
            # Setting volume to exact percentage
            res_50 = change_volume(action="set", level=50)
            self.assertIn("50%", res_50)
            curr = get_master_volume_percent()
            self.assertEqual(curr, 50)

            # Fast launcher percentage regex
            res_fast = try_fast_launch("поставь звук на 25%")
            self.assertIsNotNone(res_fast)
            self.assertIn("25%", res_fast)
            self.assertEqual(get_master_volume_percent(), 25)

            # String numeric extraction in action
            res_action_num = change_volume(action="75%")
            self.assertIn("75%", res_action_num)
            self.assertEqual(get_master_volume_percent(), 75)
        finally:
            set_master_volume_percent(orig_vol)

    def test_web_search_reliability(self):
        res = search_web("курс рубля")
        self.assertIsInstance(res, str)
        self.assertIn("Результаты поиска", res)
        self.assertNotIn("не удалось найти кратких сниппетов", res)

    def test_autostart_toggle(self):
        # Default is False
        set_autostart(False)
        self.assertFalse(is_autostart_enabled())
        # Toggle on
        set_autostart(True)
        self.assertTrue(is_autostart_enabled())
        # Toggle off back to default
        set_autostart(False)
        self.assertFalse(is_autostart_enabled())

    def test_computer_use_display_and_mouse(self):
        disp = get_display_info()
        self.assertIn("Экран:", disp)
        self.assertIn("пикселей", disp)

        res_move = mouse_move(100, 100)
        self.assertIn("Курсор перемещен", res_move)

        res_click = mouse_click(100, 100, "left", 1)
        self.assertIn("Клик (left) выполнен", res_click)

        # Verify right-click uses correct MOUSEEVENTF_RIGHTUP
        from src.tools.computer_use import MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_LEFTUP
        self.assertEqual(MOUSEEVENTF_RIGHTUP, 0x0010)
        self.assertNotEqual(MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_LEFTUP)
        res_right = mouse_click(100, 100, "right", 1)
        self.assertIn("Клик (right) выполнен", res_right)

    def test_uia_inspect_window_live(self):
        res = uia_inspect_window(max_elements=10)
        self.assertIsInstance(res, str)
        self.assertIn("Элементы интерфейса окна", res)

    def test_browser_fast_url(self):
        res = browser_open_url("example.com")
        self.assertIn("Открыта ссылка", res)
        self.assertIn("https://example.com", res)

    def test_ui_mic_indicator_vector_and_animations(self):
        mic = AnimatedMicIndicator()
        mic.show_listening("Слушаю...")
        mic._animate_pulse()
        self.assertTrue(mic.isVisible())
        mic.set_partial_text("Тестовый голос")
        self.assertEqual(mic.displayed_text, "Тестовый голос")
        mic.hide_listening()
        self.assertFalse(mic.isVisible())

    def test_volume_clamping_and_validation(self):
        orig_vol = get_master_volume_percent()
        try:
            # Clamping below 0
            set_master_volume_percent(-20)
            self.assertEqual(get_master_volume_percent(), 0)

            # Clamping above 100
            set_master_volume_percent(180)
            self.assertEqual(get_master_volume_percent(), 100)

            # String numeric
            set_master_volume_percent("45")
            self.assertEqual(get_master_volume_percent(), 45)

            # Invalid string handled gracefully
            res_invalid = set_master_volume_percent("абвгд")
            self.assertIn("Неверный уровень громкости", res_invalid)
        finally:
            set_master_volume_percent(orig_vol)

    def test_gemini_history_preservation_on_key_rotation(self):
        from src.services.gemini_service import gemini_service
        # Simulate chat with mock history
        fake_history = ["user: Привет, меня зовут Хамид", "model: Привет Хамид! Чем могу помочь?"]
        gemini_service.chat = unittest.mock.MagicMock()
        gemini_service.chat.get_history.return_value = fake_history

        # Ensure next key rotation keeps history
        with unittest.mock.patch.object(gemini_service, "start_new_chat") as mock_start:
            gemini_service._ensure_next_round_robin_client()
            self.assertTrue(mock_start.called)
            # Verify history was passed to new chat
            call_kwargs = mock_start.call_args[1]
            self.assertEqual(call_kwargs.get("history"), fake_history)

    def test_hud_in_window_listening(self):
        hud = HUDWindow()
        self.assertFalse(hud.is_listening_ui_active())
        hud.start_listening_ui("Слушаю вас...")
        self.assertTrue(hud.is_listening_ui_active())
        self.assertTrue(hud.listening_bar.isVisible())
        hud.set_dictated_text("Привет Бомж")
        self.assertEqual(hud.prompt_input.text(), "Привет Бомж")
        hud.stop_listening_ui()
        self.assertFalse(hud.is_listening_ui_active())
        self.assertFalse(hud.listening_bar.isVisible())
        hud.close()

if __name__ == "__main__":
    unittest.main()
