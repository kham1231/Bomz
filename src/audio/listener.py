import io
import wave
import json
import re
import time
import queue
import logging
from typing import List
import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer
from PyQt6.QtCore import QThread, pyqtSignal

from src.core.config import config
from src.audio.vosk_manager import get_vosk_model

logger = logging.getLogger(__name__)

DEFAULT_WAKE_GRAMMAR: List[str] = ["бомж", "бомжик", "бонж", "компьютер", "ассистент", "[unk]"]

def is_wake_word(text: str, custom_wake: str = "бомж") -> bool:
    """Robust wake-word and alias matcher for Russian speech recognition."""
    t = text.lower().strip()
    if not t:
        return False
    base_patterns = [
        r"\bбомж\w*",
        r"\bбонж\w*",
        r"\bассистент\w*",
        r"\bкомпьютер\w*",
        r"\bкампьютер\w*",
        r"\b(?:эй|хей|слушай|привет|ок|окей)\s+(?:бог|бон|бом|бош|комп|бонж|бомж)\b",
        r"^(?:бог|бон|бом|бош|комп)$"
    ]
    if custom_wake and custom_wake.lower() not in ["бомж", "бонж", "ассистент", "компьютер"]:
        base_patterns.insert(0, rf"\b{re.escape(custom_wake.lower())}\w*")
    pattern = re.compile("|".join(base_patterns), re.IGNORECASE)
    return bool(pattern.search(t))

def clean_speech_text(text: str) -> str:
    """Cleans up wake-word prefixes and Vosk pronunciation/phoneme artifacts like '/м'."""
    cleaned = re.sub(
        r"^(?:(?:слушай|привет|эй|хей|ок|окей)\s+)?(?:бомж\w*|бонж\w*|компьютер\w*|кампьютер\w*|ассистент\w*|бог|бон|бом|бош)[\s,]*",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(r"/[a-zA-Zа-яА-Я0-9_]+", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def is_stop_phrase(text: str) -> bool:
    """
    Detects immediate stop/abort commands from user speech.
    Must be an isolated, short command (1 to 3 words max).
    Does NOT trigger if stop words are embedded in longer multi-word instructions.
    """
    t = text.lower().strip()
    if not t:
        return False
    t = clean_speech_text(t)
    stop_words = {"стоп", "остановись", "останови", "прекрати", "хватит", "отмена", "замолчи", "тихо", "молчи", "stop", "abort"}
    words = re.findall(r'[a-zA-Zа-яА-ЯёЁ]+', t)
    # Strictly check length: only isolated phrases like "стоп", "бомж стоп", "хватит", "остановись"
    if 1 <= len(words) <= 3 and any(w in stop_words for w in words):
        return True
    return False

PARASITIC_FRAGMENTS = {"можешь", "ну", "а", "да", "нет", "э", "мм", "слушай", "так", "щас", "ща"}

def pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
    """Encodes raw 16-bit mono PCM into standard WAV bytes in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()

class AudioListenerThread(QThread):
    """
    Background worker thread capturing audio from microphone.
    Operates in two specialized modes:
    1. Grammar-Constrained KWS (Keyword Spotting) for ultra-accurate, near-zero CPU wake-word detection
       (["бомж", "бомжик", "бонж", "компьютер", "ассистент", "[unk]"]).
    2. Dynamic VAD / Adaptive Silence Cutoff (350-400ms) for instant speech capture and audio streaming to Gemini.
    """
    wake_word_detected = pyqtSignal()
    listening_started = pyqtSignal()
    listening_stopped = pyqtSignal()                 # Emitted when listening cancels, stops or times out without speech
    stop_requested = pyqtSignal()                    # Immediate user abort command ('стоп', 'остановись', 'хватит')
    follow_up_started = pyqtSignal()
    follow_up_ended = pyqtSignal()
    partial_text_updated = pyqtSignal(str)
    voice_command_captured = pyqtSignal(bytes, str)  # (wav_bytes, fallback_text)
    command_recognized = pyqtSignal(str)
    audio_level_updated = pyqtSignal(float)          # Normalized mic RMS energy (0.0 to 1.0)
    error_occurred = pyqtSignal(str)

    STATE_WAKE_WORD = "WAKE_WORD"
    STATE_COMMAND = "COMMAND"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.state = self.STATE_WAKE_WORD
        self.audio_queue = queue.Queue()
        self.sample_rate = 16000
        self.model = None
        self.wake_recognizer = None
        self.cmd_recognizer = None
        self.recognizer = None

        # Build grammar list with user-configured wake word and aliases
        self.wake_grammar = list(DEFAULT_WAKE_GRAMMAR)
        user_wake = config.get("wake_word", "бомж").lower().strip()
        if user_wake and user_wake not in self.wake_grammar:
            self.wake_grammar.insert(0, user_wake)

        self.wake_word = user_wake or "бомж"
        
        self.is_follow_up = False
        self.speech_detected = False
        self.speech_start_time = 0
        self.last_speech_time = 0
        self.command_started_time = 0
        
        # Adaptive VAD parameters
        self.initial_wait_timeout_sec = 3.8
        self.follow_up_timeout_sec = 5.0
        # Ultra-fast adaptive silence cutoff (380 ms instead of 1.5s delay)
        self.silence_threshold_sec = 0.38
        self.max_command_duration_sec = 12.0
        self.noise_floor = 180.0
        self.dynamic_speech_threshold = 350.0
        
        self.accumulated_command = []
        self.current_partial = ""
        self.recorded_pcm = bytearray()

    def run(self):
        self.running = True
        logger.info("[AudioListener] Initializing Vosk model and Kaldi recognizers...")
        try:
            self.model = get_vosk_model()
            # Standard full-vocabulary recognizers for Russian Vosk small-ru model.
            # (Note: vosk-model-small-ru-0.22 does not support dynamic grammar JSON;
            # we use standard KaldiRecognizer with fast phoneme-alias regex matching).
            self.wake_recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.cmd_recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.cmd_recognizer.SetWords(True)

            self.recognizer = self.wake_recognizer
            logger.info(f"[AudioListener] Vosk recognizers initialized successfully.")
        except Exception as e:
            err = f"Ошибка загрузки модели Vosk: {e}"
            logger.error(f"[AudioListener] {err}")
            self.error_occurred.emit(err)
            return

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"[AudioListener] Stream status: {status}")
            self.audio_queue.put(bytes(indata))

        try:
            with sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=4000,
                dtype="int16",
                channels=1,
                callback=audio_callback
            ):
                logger.info("[AudioListener] Listening for wake words (Grammar KWS active)...")
                while self.running:
                    try:
                        data = self.audio_queue.get(timeout=0.08)
                    except queue.Empty:
                        if self.state == self.STATE_COMMAND:
                            self._check_command_timeout()
                        continue

                    self._process_audio_chunk(data)

        except Exception as e:
            err = f"Ошибка микрофона: {e}"
            logger.error(f"[AudioListener] {err}")
            self.error_occurred.emit(err)

    def trigger_manual_listen(self):
        """Called when hotkey or mic button is clicked."""
        logger.info("[AudioListener] Manual listen triggered.")
        self.state = self.STATE_COMMAND
        self.recognizer = self.cmd_recognizer
        self.is_follow_up = False
        self.speech_detected = False
        self.speech_start_time = 0
        self.command_started_time = time.time()
        self.last_speech_time = time.time()
        self.accumulated_command = []
        self.current_partial = ""
        self.recorded_pcm.clear()
        if self.cmd_recognizer:
            self.cmd_recognizer.Reset()
        self.listening_started.emit()

    def trigger_follow_up(self, timeout_sec: float = 5.0):
        """Puts listener into continuous dialogue mode (waiting for speech without saying 'Бомж')."""
        logger.info(f"[AudioListener] Entering follow-up mode ({timeout_sec}s)...")
        self.state = self.STATE_COMMAND
        self.recognizer = self.cmd_recognizer
        self.is_follow_up = True
        self.follow_up_timeout_sec = timeout_sec
        self.speech_detected = False
        self.speech_start_time = 0
        self.command_started_time = time.time()
        self.last_speech_time = time.time()
        self.accumulated_command = []
        self.current_partial = ""
        self.recorded_pcm.clear()
        if self.cmd_recognizer:
            self.cmd_recognizer.Reset()
        self.follow_up_started.emit()

    def _process_audio_chunk(self, data: bytes):
        # Measure audio energy (RMS) for Dynamic VAD and live visualizer
        audio_array = np.frombuffer(data, dtype=np.int16)
        rms = float(np.sqrt(np.mean(audio_array.astype(float)**2))) if len(audio_array) > 0 else 0.0

        # Adaptively track ambient noise floor
        if not self.speech_detected:
            self.noise_floor = self.noise_floor * 0.93 + rms * 0.07
            self.dynamic_speech_threshold = max(320.0, self.noise_floor * 2.2)
        else:
            self.dynamic_speech_threshold = max(280.0, self.noise_floor * 1.6)

        # Emit normalized mic level for real-time visualizer (0.0 to 1.0)
        norm_level = float(min(1.0, max(0.0, (rms - self.noise_floor) / 900.0)))
        self.audio_level_updated.emit(norm_level)

        if not self.recognizer and not self.wake_recognizer and not self.cmd_recognizer:
            return

        if self.state == self.STATE_WAKE_WORD:
            active_rec = self.wake_recognizer or self.recognizer
            is_final = active_rec.AcceptWaveform(data)

            text = ""
            if is_final:
                res = json.loads(active_rec.Result())
                text = res.get("text", "").lower()
            else:
                res = json.loads(active_rec.PartialResult())
                text = res.get("partial", "").lower()

            if text and is_stop_phrase(text):
                logger.info(f"[AudioListener] Stop phrase recognized in wake state: '{text}'!")
                self.stop_requested.emit()
                self._reset_to_wake_word(notify_ui=True)
                return

            if text and is_wake_word(text, self.wake_word):
                logger.info(f"[AudioListener] Wake word recognized: '{text}'!")
                active_rec.Reset()
                if self.cmd_recognizer:
                    self.cmd_recognizer.Reset()
                self.recognizer = self.cmd_recognizer

                self.accumulated_command = []
                self.current_partial = ""
                self.recorded_pcm.clear()
                
                self.state = self.STATE_COMMAND
                self.is_follow_up = False
                self.command_started_time = time.time()
                self.last_speech_time = time.time()

                # If wake phrase contained one-breath user command (e.g. "бомж открой блокнот")
                remainder = clean_speech_text(text)
                if remainder:
                    logger.info(f"[AudioListener] One-breath command detected in wake phrase: '{remainder}'")
                    self.accumulated_command.append(remainder)
                    self.speech_detected = True
                    self.speech_start_time = time.time()
                else:
                    self.speech_detected = False
                    self.speech_start_time = 0

                self.wake_word_detected.emit()
                self.listening_started.emit()
                if remainder:
                    self.partial_text_updated.emit(remainder)

        elif self.state == self.STATE_COMMAND:
            active_rec = self.cmd_recognizer or self.recognizer
            is_final = active_rec.AcceptWaveform(data)

            # Accumulate raw audio frames into buffer for Gemini Multimodal Audio
            self.recorded_pcm.extend(data)

            # Dynamic VAD voice detection
            if rms > self.dynamic_speech_threshold:
                if not self.speech_detected:
                    self.speech_detected = True
                    self.speech_start_time = time.time()
                    logger.info(f"[AudioListener] Voice detected via Dynamic VAD (RMS {rms:.1f} > threshold {self.dynamic_speech_threshold:.1f}).")
                self.last_speech_time = time.time()

            if is_final:
                res = json.loads(active_rec.Result())
                chunk_text = res.get("text", "").strip()
                if chunk_text:
                    if is_stop_phrase(chunk_text):
                        logger.info(f"[AudioListener] Stop phrase recognized in command state: '{chunk_text}'!")
                        self.stop_requested.emit()
                        self._reset_to_wake_word(notify_ui=True)
                        return
                    cleaned = clean_speech_text(chunk_text)
                    if cleaned:
                        if not self.speech_detected:
                            self.speech_detected = True
                            self.speech_start_time = time.time()
                        self.accumulated_command.append(cleaned)
                        self.current_partial = ""
                        self.last_speech_time = time.time()
                        full_str = " ".join(self.accumulated_command).strip()
                        self.partial_text_updated.emit(full_str)
            else:
                res = json.loads(active_rec.PartialResult())
                partial = res.get("partial", "").strip()
                if partial:
                    cleaned_p = clean_speech_text(partial)
                    if cleaned_p:
                        if not self.speech_detected:
                            self.speech_detected = True
                            self.speech_start_time = time.time()
                        self.current_partial = cleaned_p
                        self.last_speech_time = time.time()
                        full_str = " ".join(self.accumulated_command + [cleaned_p]).strip()
                        self.partial_text_updated.emit(full_str)

            self._check_command_timeout()

    def _check_command_timeout(self):
        now = time.time()
        time_since_command_start = now - self.command_started_time

        # 1. User hasn't started speaking yet
        if not self.speech_detected:
            timeout_limit = self.follow_up_timeout_sec if self.is_follow_up else self.initial_wait_timeout_sec
            if time_since_command_start >= timeout_limit:
                if self.is_follow_up:
                    logger.info("[AudioListener] Follow-up silence timeout. Returning to wake word.")
                    self.follow_up_ended.emit()
                else:
                    logger.info("[AudioListener] Initial speech timeout (no voice for 3.8s). Resetting.")
                self._reset_to_wake_word(notify_ui=True)
            return

        # 2. User has started speaking: detect pause via Dynamic VAD
        silence_duration = now - self.last_speech_time
        speech_duration = self.last_speech_time - (self.speech_start_time or self.command_started_time)

        parts = [p for p in self.accumulated_command if p.strip()]
        if self.current_partial.strip() and self.current_partial.strip() not in parts:
            parts.append(self.current_partial.strip())
            
        full_query = " ".join(parts).strip()
        full_query = clean_speech_text(full_query)

        # Immediate abort on spoken stop phrase
        if full_query and is_stop_phrase(full_query):
            logger.info(f"[AudioListener] Stop command recognized in full query: '{full_query}'!")
            self.stop_requested.emit()
            self._reset_to_wake_word(notify_ui=True)
            return

        # Check if the captured speech is merely an isolated introductory fragment (e.g. "можешь", "ну", "а")
        is_isolated_parasite = full_query.lower() in PARASITIC_FRAGMENTS and speech_duration < 1.2

        # Ignore brief transient noise spikes (clicks, taps < 0.20s without recognized words or < 12000 bytes PCM)
        is_transient_spike = (speech_duration < 0.25 and not full_query) or (len(self.recorded_pcm) < 12000 and len(full_query) < 3)

        # Immediate trigger once silence lasts >= 380 ms after user spoke (with genuine speech or recognized query)
        if silence_duration >= self.silence_threshold_sec:
            if not is_transient_spike and not is_isolated_parasite and (speech_duration >= 0.25 or full_query):
                logger.info(f"[AudioListener] Voice query captured via Dynamic VAD ({len(self.recorded_pcm)} PCM bytes, speech {speech_duration:.2f}s, silence {silence_duration*1000:.0f}ms). Fallback: '{full_query}'")
                wav_bytes = pcm_to_wav(bytes(self.recorded_pcm), self.sample_rate)
                self.voice_command_captured.emit(wav_bytes, full_query)
                self.command_recognized.emit(full_query)
                self._reset_to_wake_word(notify_ui=False)
            elif time_since_command_start >= (self.follow_up_timeout_sec if self.is_follow_up else self.initial_wait_timeout_sec):
                # Transient noise or abandoned introductory word timed out without actual command
                logger.info("[AudioListener] Command timeout expired without full instruction. Resetting.")
                self._reset_to_wake_word(notify_ui=True)
            
        elif time_since_command_start >= self.max_command_duration_sec:
            if len(self.recorded_pcm) >= 12000 and not is_transient_spike:
                wav_bytes = pcm_to_wav(bytes(self.recorded_pcm), self.sample_rate)
                self.voice_command_captured.emit(wav_bytes, full_query)
                self.command_recognized.emit(full_query)
                self._reset_to_wake_word(notify_ui=False)
            else:
                self._reset_to_wake_word(notify_ui=True)

    def _reset_to_wake_word(self, notify_ui: bool = True):
        self.state = self.STATE_WAKE_WORD
        self.is_follow_up = False
        self.speech_detected = False
        self.speech_start_time = 0
        self.accumulated_command = []
        self.current_partial = ""
        self.recorded_pcm.clear()
        if self.wake_recognizer:
            self.wake_recognizer.Reset()
        if self.cmd_recognizer:
            self.cmd_recognizer.Reset()
        self.recognizer = self.wake_recognizer
        if notify_ui:
            self.listening_stopped.emit()

    def stop(self):
        self.running = False
        self.wait()
