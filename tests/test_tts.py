import unittest
from src.services.tts_service import clean_text_for_tts, tts_service, AVAILABLE_SPEAKERS

class TestTTS(unittest.TestCase):
    def test_clean_text(self):
        raw = "### Заголовок\nЭто **жирный** текст с `кодом` и ```python\nprint(1)\n```!"
        cleaned = clean_text_for_tts(raw)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("```", cleaned)
        self.assertIn("Это жирный текст", cleaned)

    def test_speakers(self):
        self.assertIn("aidar", AVAILABLE_SPEAKERS)
        self.assertIn("xenia", AVAILABLE_SPEAKERS)
        tts_service.set_speaker("xenia")
        self.assertEqual(tts_service.get_speaker(), "xenia")
        tts_service.set_speaker("aidar")

if __name__ == "__main__":
    unittest.main()
