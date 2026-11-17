import unittest
from src.services.gemini_service import GeminiService

class TestGemini(unittest.TestCase):
    def setUp(self):
        self.service = GeminiService()

    def test_streaming_flash_lite(self):
        self.service.set_model("gemini-3.5-flash-lite")
        chunks = list(self.service.stream_prompt("Ответь одним словом: Тест"))
        full_text = "".join(chunks)
        self.assertTrue(len(full_text) > 0)
        print(f"\n[Test Gemini 3.5 Flash Lite]: {full_text}")

    def test_streaming_hydrogen(self):
        self.service.set_model("gemini-4-hydrogen")
        chunks = list(self.service.stream_prompt("Ответь одним словом: Работает"))
        full_text = "".join(chunks)
        self.assertTrue(len(full_text) > 0)
        print(f"\n[Test Gemini 4 Hydrogen]: {full_text}")

if __name__ == "__main__":
    unittest.main()
