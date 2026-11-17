import unittest
from src.core.config import ConfigManager

class TestConfig(unittest.TestCase):
    def test_config_defaults(self):
        cfg = ConfigManager()
        self.assertIsNotNone(cfg.get("api_key"))
        self.assertIn("gemini-3.5-flash-lite", cfg.get("available_models"))
        self.assertIn("gemini-4-hydrogen", cfg.get("available_models"))
        self.assertEqual(cfg.get("wake_word"), "бомж")

    def test_toggle_model(self):
        cfg = ConfigManager()
        initial = cfg.get("active_model")
        next_model = cfg.toggle_model()
        self.assertNotEqual(initial, next_model)
        # Restore initial
        cfg.set("active_model", initial)

if __name__ == "__main__":
    unittest.main()
