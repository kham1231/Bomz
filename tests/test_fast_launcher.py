import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from src.tools.fast_launcher import try_fast_launch, execute_fast_command, SemanticIntentEngine
from src.audio.listener import AudioListenerThread

class TestFastLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    @patch("os.startfile")
    @patch("src.tools.fast_launcher._spawn_detached")
    def test_fast_launch_match(self, mock_spawn, mock_startfile):
        # We don't actually open windows during test, mock execution
        res = try_fast_launch("бомж, открой настройки пожалуйста")
        self.assertIsNotNone(res)
        self.assertIn("Открываю", res)
        mock_startfile.assert_called_once_with("ms-settings:")

        res_calc = try_fast_launch("открой калькулятор")
        self.assertIsNotNone(res_calc)
        self.assertIn("Открываю", res_calc)
        self.assertTrue(mock_spawn.called)

        # Max / min volume fast shortcuts
        res_max = try_fast_launch("поставь звук на максимум")
        self.assertIsNotNone(res_max)
        self.assertIn("100%", res_max)

        res_min = try_fast_launch("звук в ноль")
        self.assertIsNotNone(res_min)
        self.assertIn("0%", res_min)

        res_non_match = try_fast_launch("какая сегодня погода в Москве?")
        self.assertIsNone(res_non_match)

    @patch("os.startfile")
    @patch("src.tools.fast_launcher._spawn_detached")
    def test_semantic_intent_natural_speech(self, mock_spawn, mock_startfile):
        """Tests that natural speech variations without hardcoded keywords match correctly."""
        # 1. Volume down variations
        res_down1 = try_fast_launch("слушай, сделай-ка музло потише")
        self.assertIsNotNone(res_down1)
        self.assertIn("уменьшена", res_down1)

        res_down2 = try_fast_launch("приглуши звук")
        self.assertIsNotNone(res_down2)
        self.assertIn("уменьшена", res_down2)

        # 2. Volume up variations
        res_up1 = try_fast_launch("навали музла")
        self.assertIsNotNone(res_up1)
        self.assertIn("увеличена", res_up1)

        res_up2 = try_fast_launch("сделай музыку погромче")
        self.assertIsNotNone(res_up2)
        self.assertIn("увеличена", res_up2)

        # 3. Mute / Unmute
        res_mute = try_fast_launch("заглуши")
        self.assertIsNotNone(res_mute)
        self.assertIn("выключен", res_mute)

        res_unmute = try_fast_launch("верни звук")
        self.assertIsNotNone(res_unmute)
        self.assertIn("включен", res_unmute)

        # 4. Media control
        res_pause = try_fast_launch("поставь на паузу музон")
        self.assertIsNotNone(res_pause)
        self.assertIn("Воспроизведение / Пауза", res_pause)

        res_next = try_fast_launch("след трек")
        self.assertIsNotNone(res_next)
        self.assertIn("следующий трек", res_next.lower())

        # 1c. Russian word-number exact volume
        res_ru_vol = try_fast_launch("поставь звук на пятьдесят")
        self.assertIsNotNone(res_ru_vol)
        self.assertIn("50%", res_ru_vol)

        res_ru_vol2 = try_fast_launch("громкость двадцать процентов")
        self.assertIsNotNone(res_ru_vol2)
        self.assertIn("20%", res_ru_vol2)

        # 1d. Wake-word prefixed natural speech
        res_prefix = try_fast_launch("привет бомжик открой блокнот")
        self.assertIsNotNone(res_prefix)
        self.assertIn("Открываю блокнот", res_prefix)

        # 5. Window control
        res_win = try_fast_launch("спрячь все окна быстро")
        self.assertIsNotNone(res_win)
        self.assertIn("Все окна свернуты", res_win)

        res_close_win = try_fast_launch("закрой это окно")
        self.assertIsNotNone(res_close_win)
        self.assertIn("Активное окно закрыто", res_close_win)

        # 6. Natural app launch
        res_browser = try_fast_launch("вруби мне браузерку")
        self.assertIsNotNone(res_browser)
        self.assertIn("Открываю браузер", res_browser)

        res_calc = try_fast_launch("стартони калькулятор")
        self.assertIsNotNone(res_calc)
        self.assertIn("Открываю калькулятор", res_calc)

        # 7. Natural app close
        res_kill_calc = try_fast_launch("выруби калькулятор")
        self.assertIsNotNone(res_kill_calc)
        self.assertIn("Закрываю калькулятор", res_kill_calc)
        self.assertTrue(mock_spawn.called)

        res_kill_notepad = try_fast_launch("закрой блокнот")
        self.assertIsNotNone(res_kill_notepad)
        self.assertIn("Закрываю блокнот", res_kill_notepad)

    def test_semantic_intent_informational_pass_through(self):
        """Ensures that informational and complex questions are NOT intercepted and pass to Gemini."""
        queries = [
            "какая сегодня погода в Москве?",
            "что такое квантовая запутанность?",
            "как написать цикл for в Python?",
            "расскажи мне анекдот",
            "объясни разницу между стеком и очередью",
            "почему небо голубое?",
            "кто написал войну и мир?"
        ]
        for q in queries:
            result = try_fast_launch(q)
            self.assertIsNone(result, f"Query '{q}' should NOT be intercepted, but got: {result}")

    def test_composite_commands_pass_through_to_gemini(self):
        """
        Tests Smart Composite Command Filter:
        Multi-step commands with conjunctions ('и', 'затем', 'потом', 'после чего', 'чтобы')
        or secondary action verbs ('потыкай', 'нажми', 'посчитай', 'найди', 'введи', 'посмотри')
        must NOT be intercepted by the fast router and must pass through to Gemini.
        """
        composite_queries = [
            "открой калькулятор и посчитай 2+2",
            "открой блокнот затем напиши привет",
            "открой блокнот потом нажми enter",
            "открой браузер после чего найди погоду в Москве",
            "запусти калькулятор чтобы потыкать кнопки",
            "звук 50% и закрой хром",
            "сверни окна и открой блокнот",
            "открой блокнот напиши привет Хамиду",
            "открой калькулятор посчитай пять плюс пять",
            "открой блокнот введи текст",
            "открой хром найди документацию Python",
            "открой проводник посмотри файлы на диске C",
            "открой настройки потыкай сеть",
            "открой блокнот нажми сохранить",
            "открой хром кликни по первой ссылке",
            "открой блокнот закрой хром",
            "звук 50% закрой калькулятор",
            "открой браузер из пиши туда как сделать чучело",
            "открой браузер впиши туда погода в Сочи",
            "открой калькулятор и нажмите кнопку семь восемь плюс девять плюс одиннадцать"
        ]
        for q in composite_queries:
            result = try_fast_launch(q)
            self.assertIsNone(result, f"Composite query '{q}' should NOT be intercepted by fast launcher!")

        # Ensure atomic single commands still execute directly
        atomic_calc = try_fast_launch("открой калькулятор")
        self.assertIsNotNone(atomic_calc)
        self.assertIn("Открываю калькулятор", atomic_calc)

        atomic_vol = try_fast_launch("звук 50%")
        self.assertIsNotNone(atomic_vol)
        self.assertIn("50%", atomic_vol)

        atomic_close = try_fast_launch("закрой блокнот")
        self.assertIsNotNone(atomic_close)
        self.assertIn("Закрываю блокнот", atomic_close)

        atomic_win = try_fast_launch("сверни окна")
        self.assertIsNotNone(atomic_win)
        self.assertIn("свернуты", atomic_win)

    def test_abort_commands(self):
        """Tests instant recognition of spoken stop/abort instructions."""
        stop_phrases = ["стоп", "бомж, остановись", "прекрати", "хватит", "замолчи", "отмена", "тихо"]
        for p in stop_phrases:
            res = try_fast_launch(p)
            self.assertEqual(res, "[STOP]", f"Phrase '{p}' should trigger immediate [STOP], got {res}")

    @patch("os.startfile")
    @patch("src.tools.fast_launcher._spawn_detached")
    def test_execute_fast_command(self, mock_spawn, mock_startfile):
        res = execute_fast_command("start ms-settings:")
        self.assertIsNotNone(res)
        self.assertIn("успешно запущено", res)
        mock_startfile.assert_called_once_with("ms-settings:")

        res_calc = execute_fast_command("calc.exe")
        self.assertIsNotNone(res_calc)
        self.assertTrue(mock_spawn.called)

        res_complex = execute_fast_command("Get-Process | Sort-Object CPU")
        self.assertIsNone(res_complex)

    def test_listener_follow_up_state(self):
        listener = AudioListenerThread()
        self.assertFalse(listener.is_follow_up)
        listener.trigger_follow_up(5.0)
        self.assertTrue(listener.is_follow_up)
        self.assertEqual(listener.state, listener.STATE_COMMAND)
        self.assertFalse(listener.speech_detected)

if __name__ == "__main__":
    unittest.main()
