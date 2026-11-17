import unittest
import sys
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from src.ui.hud_window import HUDWindow
from src.ui.mic_indicator import AnimatedMicIndicator
from src.ui.tray import BomzhTrayIcon

class TestUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def test_hud_instantiation(self):
        hud = HUDWindow()
        self.assertIsNotNone(hud)
        self.assertEqual(hud.window_width, 440)
        self.assertTrue(hud.container is not None)
        # Ensure HUD window has no QGraphicsDropShadowEffect attached directly (prevents Windows DWM negative dirty rect crash)
        self.assertIsNone(hud.graphicsEffect())
        self.assertIsNotNone(hud.stop_btn)
        hud.set_status("Тест готовности", "ready")
        self.assertIn("Тест готовности", hud.status_badge.text())

        # Test stop_all action
        hud.is_streaming = True
        hud.stop_all(notify_user=False)
        self.assertFalse(hud.is_streaming)
        self.assertIn("Остановлено", hud.status_badge.text())

        # Test query header extraction logic with mocked background audio stream
        with patch("src.services.gemini_service.gemini_service.stream_audio_prompt", return_value=[]):
            hud.send_audio_query(b"RIFF...", fallback_query="резервный запрос")
            self.assertFalse(hud.query_extracted)
            hud._on_token_received("QUERY: Ассаламу алейкум, как дела?\n")
            self.assertTrue(hud.query_extracted)
            self.assertEqual(hud.prompt_input.text(), "Ассаламу алейкум, как дела?")
            hud._on_token_received("Ваалейкум ассалам!")
            self.assertIn("Ваалейкум", hud.response_text)
            hud.close()

    @patch("src.tools.fast_launcher._spawn_detached")
    @patch("os.startfile")
    def test_hud_fast_command_bypasses_gemini(self, mock_startfile, mock_spawn):
        hud = HUDWindow()
        hud.stream_worker = None

        # 1. send_query with fast hardware command should execute locally without Gemini
        hud.send_query("открой блокнот")
        self.assertIsNone(hud.stream_worker, "GeminiStreamWorker must NOT be created for fast local commands!")
        self.assertIn("Открываю блокнот", hud.response_text)
        self.assertFalse(hud.is_streaming)

        # 2. send_audio_query with recognized fast fallback query should also execute locally without Gemini
        hud.send_audio_query(b"FAKE_WAV", fallback_query="сделай звук тише")
        self.assertIsNone(hud.stream_worker, "GeminiStreamWorker must NOT be created when speech fallback matches fast intent!")
        self.assertIn("уменьшена", hud.response_text)
        self.assertFalse(hud.is_streaming)

        # 3. send_query with composite command should NOT be intercepted locally and MUST launch GeminiStreamWorker
        with patch("src.services.gemini_service.gemini_service.stream_prompt", return_value=["OK"]):
            hud.send_query("открой блокнот и напиши привет")
            self.assertIsNotNone(hud.stream_worker, "GeminiStreamWorker MUST be created for composite commands!")
            self.assertTrue(hud.is_streaming)
            hud._stop_stream_worker()

        hud.close()

    def test_mic_indicator(self):
        mic = AnimatedMicIndicator()
        self.assertIsNotNone(mic)
        # Ensure no QGraphicsDropShadowEffect is attached to avoid Windows DWM UpdateLayeredWindowIndirect failure
        self.assertIsNone(mic.graphicsEffect())
        mic.show_listening("Слушаю...")
        self.assertEqual(mic.displayed_text, "Слушаю...")
        mic.set_partial_text("тестовая фраза")
        self.assertIn("тестовая", mic.displayed_text)
        mic.hide_listening()

    def test_tray_instantiation(self):
        tray = BomzhTrayIcon()
        self.assertIsNotNone(tray)
        self.assertIsNotNone(tray.menu)

    def test_history_sanitization(self):
        from google.genai import types
        from src.services.gemini_service import sanitize_conversation_history

        # Mock history with heavy inline screenshots and 3 dialogue turns
        mock_history = [
            types.Content(role="user", parts=[
                types.Part.from_bytes(data=b"FAKE_JPEG_IMAGE" * 500, mime_type="image/jpeg"),
                types.Part.from_text(text="что на экране?")
            ]),
            types.Content(role="model", parts=[
                types.Part.from_text(text="Вижу рабочий стол.")
            ]),
            types.Content(role="user", parts=[
                types.Part.from_text(text="открой калькулятор")
            ]),
            types.Content(role="model", parts=[
                types.Part.from_text(text="Калькулятор открыт.")
            ]),
            types.Content(role="user", parts=[
                types.Part.from_text(text="посчитай 5 на 5")
            ]),
            types.Content(role="model", parts=[
                types.Part.from_text(text="25.")
            ])
        ]

        cleaned = sanitize_conversation_history(mock_history, max_turns=2)
        self.assertEqual(len(cleaned), 4)
        for c in cleaned:
            for p in c.parts:
                self.assertIsNone(p.inline_data)
                self.assertIsNotNone(p.text)
        # Check last turn text preserved
        self.assertEqual(cleaned[-2].parts[0].text, "посчитай 5 на 5")
        self.assertEqual(cleaned[-1].parts[0].text, "25.")

if __name__ == "__main__":
    unittest.main()
