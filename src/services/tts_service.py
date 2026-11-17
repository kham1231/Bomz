import os
import sys
import ctypes
import re
import queue
import logging
import threading
from pathlib import Path
from typing import Optional, Callable
import torch
import numpy as np
import sounddevice as sd

from src.core.config import config

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_MODEL_PATH = BASE_DIR / "models" / "silero" / "v5_6_ru.pt"
CACHE_MODEL_PATH = Path(r"C:\Users\MyPC\.cache\torch\hub\snakers4_silero-models_master\src\silero\model\v5_6_ru.pt")

AVAILABLE_SPEAKERS = ["aidar", "xenia", "baya", "kseniya", "eugene"]

_END_OF_STREAM_SENTINEL = object()

def get_safe_path(p: Path) -> str:
    """Converts a Windows path to an 8.3 short path to avoid Cyrillic encoding issues with C++ fopen."""
    path_str = str(p.resolve())
    if sys.platform == "win32":
        try:
            buf = ctypes.create_unicode_buffer(1024)
            ret = ctypes.windll.kernel32.GetShortPathNameW(path_str, buf, 1024)
            if ret > 0 and buf.value:
                return buf.value
        except Exception as e:
            logger.warning(f"[TTS] Short path conversion error: {e}")
    return path_str

def clean_text_for_tts(text: str) -> str:
    """Strips markdown, code blocks, URLs, and symbols for natural voice synthesis."""
    if not text:
        return ""
    # Remove code blocks
    cleaned = re.sub(r"```[\s\S]*?```", " код пропущен ", text)
    # Remove inline code
    cleaned = re.sub(r"`[^`]*`", "", cleaned)
    # Remove markdown links [title](url) -> title
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    # Remove headers, bullets, markup
    cleaned = re.sub(r"[#*_\~`>\[\]]", "", cleaned)
    # Remove emojis and odd symbols
    cleaned = re.sub(r"[^\w\s.,!?;:—–-]", "", cleaned)
    # Normalize spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

class SileroTTSService:
    """
    Local offline Russian text-to-speech using Silero v5.6.
    Supports Sentence-Level Streaming TTS with pipelined synthesis & playback queue
    to start voice output within 500-700ms from the beginning of generation.
    """
    def __init__(self):
        self.sample_rate = 24000
        self.device = torch.device("cpu")
        self.model = None
        self._is_loading = False
        self._lock = threading.Lock()

        # Two-stage pipelined queues:
        # 1. Text sentences waiting to be synthesized by Silero
        self.sentence_queue: queue.Queue = queue.Queue()
        # 2. Synthesized audio arrays waiting to be played by sounddevice
        self.playback_queue: queue.Queue = queue.Queue()

        self.playback_finished_callback: Optional[Callable[[], None]] = None
        self._is_streaming_active = False
        self._stream_text_buffer = ""
        self._stream_lock = threading.Lock()
        self._is_playing = False
        self._interrupted = False

        # Start background workers for pipelined synthesis and playback
        self.synthesis_worker_thread = threading.Thread(target=self._synthesis_worker, daemon=True)
        self.synthesis_worker_thread.start()

        self.playback_worker_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self.playback_worker_thread.start()

        # If already enabled in config, warm up model in background
        if self.is_enabled():
            threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        if self.model is not None or self._is_loading:
            return
        with self._lock:
            if self.model is not None:
                return
            self._is_loading = True
            try:
                target_path = None
                if LOCAL_MODEL_PATH.exists():
                    target_path = LOCAL_MODEL_PATH
                elif CACHE_MODEL_PATH.exists():
                    target_path = CACHE_MODEL_PATH

                if not target_path:
                    logger.error("[TTS] Silero model not found in local models or cache!")
                    return

                safe_path = get_safe_path(target_path)
                logger.info(f"[TTS] Loading Silero model from safe path: {safe_path}...")
                importer = torch.package.PackageImporter(safe_path)
                self.model = importer.load_pickle("tts_models", "model")
                self.model.to(self.device)

                # Warmup synthesis
                _ = self.model.apply_tts(text="Бомж готов", speaker="aidar", sample_rate=self.sample_rate)
                logger.info("[TTS] Silero model loaded and warmed up successfully!")
            except Exception as e:
                logger.error(f"[TTS] Error loading Silero model: {e}")
            finally:
                self._is_loading = False

    def is_enabled(self) -> bool:
        return config.get("tts_enabled", False)

    def set_enabled(self, enabled: bool):
        config.set("tts_enabled", enabled)
        if enabled and self.model is None:
            threading.Thread(target=self._load_model, daemon=True).start()

    def get_speaker(self) -> str:
        return config.get("tts_speaker", "aidar")

    def set_speaker(self, speaker: str):
        if speaker in AVAILABLE_SPEAKERS:
            config.set("tts_speaker", speaker)

    # --- Sentence-Level Streaming API ---

    def start_stream_session(self):
        """Initializes a new streaming TTS session for incoming token chunks."""
        if not self.is_enabled():
            return
        with self._stream_lock:
            self._is_streaming_active = True
            self._interrupted = False
            self._stream_text_buffer = ""
            self._drain_queue(self.sentence_queue)
            self._drain_queue(self.playback_queue)
            try:
                sd.stop()
            except Exception:
                pass

    def feed_stream_token(self, token: str):
        """
        Feeds token chunk from model stream.
        Detects completed sentences on-the-fly and pushes them to synthesis immediately.
        """
        if not self.is_enabled() or not self._is_streaming_active:
            return

        with self._stream_lock:
            self._stream_text_buffer += token

            # Split on sentence boundaries: punctuation (. ! ?) followed by space/newline or double newline
            # Don't split on abbreviations (e.g. "т.д.", "руб.", numbers like "3.14")
            start_pos = 0
            while True:
                match = re.search(r'(?<=[.!?])\s+|[\r\n]{2,}', self._stream_text_buffer[start_pos:])
                if not match:
                    break

                split_idx = start_pos + match.start()
                end_idx = start_pos + match.end()
                candidate = self._stream_text_buffer[:split_idx].strip()
                after = self._stream_text_buffer[end_idx:]

                # Check for false abbreviation splits
                if re.search(r'\b(?:т\.д|т\.е|руб|г|ул|v\d+|\d+)\.$', candidate, flags=re.IGNORECASE):
                    # Not a real sentence end, scan past this dot
                    start_pos = end_idx
                    continue

                self._stream_text_buffer = after
                start_pos = 0
                cleaned = clean_text_for_tts(candidate)
                # Ensure minimum substance (at least 2 letters)
                if cleaned and re.search(r'[a-zA-Zа-яА-ЯёЁ]', cleaned) and len(cleaned) >= 2:
                    self.sentence_queue.put(cleaned)

    def finish_stream_session(self):
        """Finalizes the streaming session, flushing any remaining buffer text."""
        if not self.is_enabled():
            return

        with self._stream_lock:
            self._is_streaming_active = False
            if self._stream_text_buffer.strip():
                cleaned = clean_text_for_tts(self._stream_text_buffer.strip())
                if cleaned and re.search(r'[a-zA-Zа-яА-ЯёЁ]', cleaned) and len(cleaned) >= 2:
                    self.sentence_queue.put(cleaned)
                self._stream_text_buffer = ""
            # Signal end of stream
            self.sentence_queue.put(_END_OF_STREAM_SENTINEL)

    def speak(self, text: str):
        """Queues complete text to be synthesized and spoken asynchronously."""
        if not self.is_enabled():
            return
        self.start_stream_session()
        self.feed_stream_token(text)
        self.finish_stream_session()

    def stop(self):
        """Immediately halts any speech synthesis & playback and drains all queues."""
        self._interrupted = True
        self.playback_finished_callback = None
        with self._stream_lock:
            self._is_streaming_active = False
            self._stream_text_buffer = ""
        self._drain_queue(self.sentence_queue)
        self._drain_queue(self.playback_queue)
        try:
            sd.stop()
        except Exception:
            pass
        self._is_playing = False

    @staticmethod
    def _drain_queue(q: queue.Queue):
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break

    # --- Pipelined Background Workers ---

    def _synthesis_worker(self):
        """Worker 1: Asynchronously turns sentences into audio numpy arrays."""
        while True:
            item = self.sentence_queue.get()
            if item is _END_OF_STREAM_SENTINEL:
                self.playback_queue.put(_END_OF_STREAM_SENTINEL)
                continue

            sentence_text = str(item)
            try:
                if self.model is None:
                    self._load_model()
                    if self.model is None:
                        continue

                speaker = self.get_speaker()
                audio_tensor = self.model.apply_tts(
                    text=sentence_text,
                    speaker=speaker,
                    sample_rate=self.sample_rate
                )
                audio_np = audio_tensor.numpy()
                self.playback_queue.put(audio_np)
            except Exception as e:
                logger.error(f"[TTS] Synthesis error for '{sentence_text[:30]}...': {e}")

    def _playback_worker(self):
        """Worker 2: Plays synthesized audio arrays sequentially through speakers."""
        while True:
            item = self.playback_queue.get()
            if item is _END_OF_STREAM_SENTINEL:
                if self.sentence_queue.empty() and self.playback_queue.empty() and not self._is_streaming_active:
                    self._is_playing = False
                    if not self._interrupted and self.playback_finished_callback:
                        try:
                            self.playback_finished_callback()
                        except Exception as cb_err:
                            logger.warning(f"[TTS] Finished callback error: {cb_err}")
                continue

            audio_np = item
            if not isinstance(audio_np, np.ndarray):
                continue

            try:
                self._is_playing = True
                sd.play(audio_np, self.sample_rate)
                sd.wait()
            except Exception as e:
                logger.error(f"[TTS] Playback error: {e}")
            finally:
                if self.sentence_queue.empty() and self.playback_queue.empty() and not self._is_streaming_active:
                    self._is_playing = False
                    if not self._interrupted and self.playback_finished_callback:
                        try:
                            self.playback_finished_callback()
                        except Exception as cb_err:
                            logger.warning(f"[TTS] Finished callback error: {cb_err}")

tts_service = SileroTTSService()
