import unittest
import numpy as np
from PyQt6.QtWidgets import QApplication
from src.audio.listener import (
    AudioListenerThread,
    clean_speech_text,
    is_wake_word,
    is_stop_phrase,
    pcm_to_wav,
    DEFAULT_WAKE_GRAMMAR
)

class TestAudioSpeedAndWakeWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_wake_grammar_aliases(self):
        listener = AudioListenerThread()
        # Verify grammar includes all target aliases
        expected = ["бомж", "бомжик", "бонж", "компьютер", "ассистент", "[unk]"]
        for word in expected:
            self.assertIn(word, listener.wake_grammar)

    def test_is_wake_word_matcher(self):
        # Comprehensive test for wake word aliases and phonetic variants
        self.assertTrue(is_wake_word("бомж"))
        self.assertTrue(is_wake_word("бомжик"))
        self.assertTrue(is_wake_word("бонж"))
        self.assertTrue(is_wake_word("компьютер"))
        self.assertTrue(is_wake_word("ассистент"))
        self.assertTrue(is_wake_word("ассистентка"))
        self.assertTrue(is_wake_word("эй бомж"))
        self.assertTrue(is_wake_word("слушай бом"))
        self.assertTrue(is_wake_word("бог"))
        self.assertTrue(is_wake_word("бон"))
        self.assertFalse(is_wake_word("привет как дела"))
        self.assertFalse(is_wake_word("включи музыку пожалуйста"))

    def test_listening_stopped_signal_on_reset(self):
        listener = AudioListenerThread()
        stopped_events = []
        listener.listening_stopped.connect(lambda: stopped_events.append(True))
        listener._reset_to_wake_word(notify_ui=True)
        self.assertEqual(len(stopped_events), 1)

    def test_dynamic_vad_silence_threshold(self):
        listener = AudioListenerThread()
        # Dynamic VAD silence threshold must be in the 350-400ms range (0.35 - 0.40s)
        self.assertGreaterEqual(listener.silence_threshold_sec, 0.35)
        self.assertLessEqual(listener.silence_threshold_sec, 0.40)

    def test_clean_speech_text_aliases(self):
        # Cleans various wake-word aliases and vosk phonetic artifacts
        self.assertEqual(clean_speech_text("бомж открой блокнот"), "открой блокнот")
        self.assertEqual(clean_speech_text("бомжик сделай звук тише"), "сделай звук тише")
        self.assertEqual(clean_speech_text("компьютер сколько времени"), "сколько времени")
        self.assertEqual(clean_speech_text("ассистент выключи музыку"), "выключи музыку")
        self.assertEqual(clean_speech_text("слушай бомж покажи экран"), "покажи экран")
        self.assertEqual(clean_speech_text("привет бомжик открой хром"), "открой хром")
        self.assertEqual(clean_speech_text("эй компьютер закрой окно"), "закрой окно")
        self.assertEqual(clean_speech_text("бомж /м привет"), "привет")

    def test_pcm_to_wav_conversion(self):
        # 1 second of 16kHz 16-bit mono PCM (zeros)
        pcm_data = bytes(32000)
        wav_bytes = pcm_to_wav(pcm_data, sample_rate=16000)
        self.assertTrue(wav_bytes.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav_bytes[:16])
        # WAV header is 44 bytes + 32000 data
        self.assertEqual(len(wav_bytes), 32044)

    def test_audio_level_normalization(self):
        listener = AudioListenerThread()
        received_levels = []
        listener.audio_level_updated.connect(received_levels.append)

        # Silent chunk
        silent_chunk = np.zeros(1000, dtype=np.int16).tobytes()
        listener._process_audio_chunk(silent_chunk)
        self.assertTrue(len(received_levels) > 0)
        self.assertAlmostEqual(received_levels[-1], 0.0, places=2)

    def test_is_stop_phrase(self):
        # Genuine isolated stop phrases (1-3 words)
        self.assertTrue(is_stop_phrase("стоп"))
        self.assertTrue(is_stop_phrase("бомж стоп"))
        self.assertTrue(is_stop_phrase("остановись"))
        self.assertTrue(is_stop_phrase("прекрати"))
        self.assertTrue(is_stop_phrase("хватит"))
        self.assertTrue(is_stop_phrase("замолчи"))
        self.assertTrue(is_stop_phrase("бомж, остановись пожалуйста"))

        # Must NOT trigger if stop word is part of a longer instruction
        self.assertFalse(is_stop_phrase("открой калькулятор и стоп"))
        self.assertFalse(is_stop_phrase("я же сказал тебя пит стоп"))
        self.assertFalse(is_stop_phrase("найди в интернете стоп кадр фильма"))
        self.assertFalse(is_stop_phrase("открой браузер и напиши рецепт"))

if __name__ == "__main__":
    unittest.main()
