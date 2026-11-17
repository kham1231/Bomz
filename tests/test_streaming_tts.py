import unittest
from src.services.tts_service import (
    clean_text_for_tts,
    SileroTTSService,
    _END_OF_STREAM_SENTINEL
)

class TestStreamingTTS(unittest.TestCase):
    def test_clean_text_for_tts(self):
        md_text = "# Заголовок\nВот **важный** [документ](http://example.com) и `код`: ```python\nprint(1)\n``` 😊"
        cleaned = clean_text_for_tts(md_text)
        self.assertNotIn("#", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("http", cleaned)
        self.assertIn("документ", cleaned)
        self.assertNotIn("😊", cleaned)
        self.assertIn("код пропущен", cleaned)

    def test_streaming_token_sentence_splitting(self):
        service = SileroTTSService()
        # Temporarily mock enabled
        service.is_enabled = lambda: True

        service.start_stream_session()
        self.assertTrue(service._is_streaming_active)
        self.assertEqual(service.sentence_queue.qsize(), 0)

        # Feed tokens piece by piece
        tokens = ["Привет, ", "Хамид! ", "Чем могу ", "помочь? ", "Вот список:\n\n1. Настройки\n\n2. Калькулятор"]
        for t in tokens:
            service.feed_stream_token(t)

        # Sentences should have been emitted into sentence_queue during streaming
        emitted_sentences = []
        while not service.sentence_queue.empty():
            emitted_sentences.append(service.sentence_queue.get())

        self.assertGreaterEqual(len(emitted_sentences), 2)
        self.assertIn("Привет, Хамид!", emitted_sentences[0])
        self.assertIn("Чем могу помочь", emitted_sentences[1])

        # Finish stream flushes the remaining buffer
        service.finish_stream_session()
        tail_items = []
        while not service.sentence_queue.empty():
            tail_items.append(service.sentence_queue.get())

        self.assertIn(_END_OF_STREAM_SENTINEL, tail_items)

    def test_streaming_abbreviations_do_not_block_stream(self):
        service = SileroTTSService()
        service.is_enabled = lambda: True
        service.start_stream_session()

        # Feed tokens with an abbreviation followed by more sentences
        service.feed_stream_token("Стоимость подписки 500 руб. Это выгодное предложение. ")
        service.feed_stream_token("Мы можем оформить его прямо сейчас! ")

        emitted = []
        while not service.sentence_queue.empty():
            emitted.append(service.sentence_queue.get())

        # The abbreviation "500 руб." should not freeze the buffer; subsequent sentences should be emitted!
        self.assertGreaterEqual(len(emitted), 2)
        self.assertIn("Это выгодное предложение", emitted[0])
        self.assertIn("Мы можем оформить его прямо сейчас", emitted[1])

    def test_stop_drains_all_queues(self):
        service = SileroTTSService()
        service.is_enabled = lambda: True
        service.sentence_queue.put("Тестовое предложение 1")
        service.sentence_queue.put("Тестовое предложение 2")
        self.assertFalse(service.sentence_queue.empty())

        service.stop()
        self.assertTrue(service.sentence_queue.empty())
        self.assertTrue(service.playback_queue.empty())
        self.assertFalse(service._is_streaming_active)

if __name__ == "__main__":
    unittest.main()
