import sys
import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from src.core.config import config
from src.core.hotkey import HotkeyListener
from src.services.gemini_service import gemini_service
from src.audio.listener import AudioListenerThread
from src.ui.hud_window import HUDWindow
from src.ui.mic_indicator import AnimatedMicIndicator
from src.ui.tray import BomzhTrayIcon

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("BomzhApp")

def main():
    logger.info("==================================================")
    logger.info("   Запуск десктоп-ассистента «Бомж» на Windows   ")
    logger.info("==================================================")

    app = QApplication(sys.argv)
    app.setApplicationName("Бомж")
    app.setOrganizationName("BomzhAI")
    
    app.setQuitOnLastWindowClosed(False)

    # Enforce default fast model (gemini-3.5-flash-lite) upon startup
    default_model = "gemini-3.5-flash-lite"
    config.set("active_model", default_model)
    gemini_service.set_model(default_model)

    # 1. Initialize UI Elements (initially hidden)
    hud_window = HUDWindow()
    mic_indicator = AnimatedMicIndicator()

    # Sync UI model display
    hud_window.update_model_chip(default_model)

    # 2. Initialize System Tray Icon
    tray_icon = BomzhTrayIcon()
    tray_icon.update_active_model(default_model)
    tray_icon.show()

    # 3. Initialize Audio Listener Thread (Vosk Wake-Word + Speech Recording)
    audio_thread = AudioListenerThread()

    # 4. Initialize Global Hotkey Listener (Ctrl + Shift + Space)
    hotkey_str = config.get("hotkey", "ctrl+shift+space")
    hotkey_listener = HotkeyListener(hotkey_str)

    # --- Wire Signals and Slots ---

    # Tray <-> HUD
    tray_icon.show_hud_requested.connect(lambda: hud_window.show_hud(animate=True))
    tray_icon.reset_dialog_requested.connect(hud_window.reset_dialog)
    tray_icon.model_switched.connect(hud_window.update_model_chip)
    hud_window.model_changed.connect(tray_icon.update_active_model)

    def on_quit():
        logger.info("[App] Quitting application...")
        hotkey_listener.stop()
        audio_thread.stop()
        tray_icon.hide()
        mic_indicator.hide_listening()
        hud_window.close()
        app.quit()

    tray_icon.quit_requested.connect(on_quit)

    # Hotkey -> Open HUD / In-HUD Mic
    def on_hotkey_pressed():
        logger.info("[App] Hotkey triggered: opening HUD and starting voice listen...")
        mic_indicator.hide_listening()
        hud_window.show_hud(start_listen=True, animate=True)
        audio_thread.trigger_manual_listen()

    hotkey_listener.hotkey_triggered.connect(on_hotkey_pressed)

    # HUD manual mic button -> In-HUD listening without hiding HUD!
    def on_hud_mic_clicked():
        logger.info("[App] HUD mic clicked: activating in-HUD listening...")
        hud_window.start_listening_ui("Слушаю вас... Говорите...")
        audio_thread.trigger_manual_listen()

    hud_window.manual_listen_requested.connect(on_hud_mic_clicked)

    # Audio -> UI Workflow
    def on_wake_word():
        if hud_window.isVisible():
            # If HUD is already open, do NOT hide it to show floating mic pill!
            # Instead activate listening animation directly inside the HUD window.
            logger.info("[App] Wake word 'Бомж' recognized with HUD open: activating in-HUD listening...")
            hud_window.start_listening_ui("Слушаю вас... Говорите...")
        else:
            # If HUD is hidden, show compact floating mic pill in top-right
            logger.info("[App] Wake word 'Бомж' recognized: showing animated mic indicator...")
            hud_window.prepare_for_new_wake_word()
            mic_indicator.show_listening("Слушаю...")

    def on_partial_text(partial: str):
        if hud_window.isVisible() and hud_window.is_listening_ui_active():
            hud_window.set_dictated_text(partial)
        elif mic_indicator.isVisible():
            mic_indicator.set_partial_text(partial)

    def on_voice_command_captured(wav_bytes: bytes, fallback_text: str):
        logger.info(f"[App] Raw voice audio captured ({len(wav_bytes)} bytes). Streaming to Gemini Multimodal Audio...")
        mic_indicator.hide_listening()
        hud_window.stop_listening_ui()
        # Open HUD smoothly (or maintain position if already open)
        is_already_visible = hud_window.isVisible()
        hud_window.show_hud(
            audio_bytes=wav_bytes,
            fallback_query=fallback_text,
            animate=not is_already_visible
        )

    def on_response_completed():
        if hud_window.isVisible():
            logger.info("[App] Response completed. Entering 5s follow-up continuous dialogue mode...")
            audio_thread.trigger_follow_up(5.0)

    def on_follow_up_started():
        logger.info("[App] Continuous dialogue active: waiting for follow-up...")
        if hud_window.isVisible():
            hud_window.start_listening_ui("Слушаю продолжение... (5с)")
        else:
            mic_indicator.show_listening("Слушаю продолжение...")

    def on_follow_up_ended():
        logger.info("[App] Continuous dialogue 5s window expired.")
        if hud_window.isVisible():
            hud_window.stop_listening_ui()
            hud_window.set_status("Готов", "ready")
        mic_indicator.hide_listening()

    def on_listening_stopped():
        logger.info("[App] Voice listening stopped or timed out without speech.")
        mic_indicator.hide_listening()
        if hud_window.isVisible():
            hud_window.stop_listening_ui()
            hud_window.set_status("Готов", "ready")

    def on_mic_indicator_clicked():
        logger.info("[App] Mic indicator clicked: opening HUD...")
        mic_indicator.hide_listening()
        hud_window.show_hud(start_listen=True, animate=True)
        audio_thread.trigger_manual_listen()

    def on_audio_error(err: str):
        logger.warning(f"[App] Audio error: {err}")
        mic_indicator.hide_listening()
        hud_window.stop_listening_ui()
        hud_window.show_hud(animate=False)
        hud_window.set_status("Микрофон недоступен", "error")

    def on_stop_requested():
        logger.info("[App] Spoken stop command detected: stopping HUD actions immediately...")
        mic_indicator.hide_listening()
        hud_window.stop_all(notify_user=True)

    mic_indicator.clicked.connect(on_mic_indicator_clicked)
    audio_thread.wake_word_detected.connect(on_wake_word)
    audio_thread.stop_requested.connect(on_stop_requested)
    audio_thread.partial_text_updated.connect(on_partial_text)
    audio_thread.audio_level_updated.connect(mic_indicator.set_audio_level)
    audio_thread.audio_level_updated.connect(hud_window.listening_bar.set_audio_level)
    audio_thread.voice_command_captured.connect(on_voice_command_captured)
    audio_thread.follow_up_started.connect(on_follow_up_started)
    audio_thread.follow_up_ended.connect(on_follow_up_ended)
    audio_thread.listening_stopped.connect(on_listening_stopped)
    audio_thread.error_occurred.connect(on_audio_error)
    hud_window.response_completed.connect(on_response_completed)

    # Start background services
    hotkey_listener.start()
    audio_thread.start()

    logger.info(f"[App] Ассистент «Бомж» запущен в фоновом режиме!")
    logger.info(f"[App] Скажите «Бомж» или нажмите {hotkey_str} для вызова.")
    logger.info(f"[App] Активная модель по умолчанию: {default_model}")

    # Initially hide both windows (stay silent in background tray)
    hud_window.hide()
    mic_indicator.hide()

    # Run Qt Event Loop
    exit_code = app.exec()

    hotkey_listener.stop()
    audio_thread.stop()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
