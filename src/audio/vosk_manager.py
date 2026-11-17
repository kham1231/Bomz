import os
import sys
import ctypes
import zipfile
import logging
import requests
from pathlib import Path
from vosk import Model, SetLogLevel

logger = logging.getLogger(__name__)

# Suppress verbose internal Vosk logs
SetLogLevel(-1)

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = BASE_DIR / "models"
MODEL_PATH = MODELS_DIR / MODEL_NAME

def get_short_path(path_str: str) -> str:
    """Converts a Windows path to an 8.3 short path to safely handle Cyrillic characters with Kaldi/Vosk C library."""
    if sys.platform == "win32":
        try:
            buf = ctypes.create_unicode_buffer(1024)
            ret = ctypes.windll.kernel32.GetShortPathNameW(str(path_str), buf, 1024)
            if ret > 0 and buf.value:
                return buf.value
        except Exception as e:
            logger.warning(f"[VoskManager] Could not convert to short path: {e}")
    return str(path_str)

def get_vosk_model(progress_callback=None) -> Model:
    """
    Returns an initialized Vosk Model for Russian.
    Downloads and extracts if not already present.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if not MODEL_PATH.exists() or not (MODEL_PATH / "am").exists():
        zip_path = MODELS_DIR / f"{MODEL_NAME}.zip"
        logger.info(f"[VoskManager] Model not found locally. Downloading from {MODEL_URL}...")
        
        response = requests.get(MODEL_URL, stream=True, timeout=60)
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(int((downloaded / total_size) * 100))
        
        logger.info("[VoskManager] Download complete. Extracting model...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(MODELS_DIR)
        
        if zip_path.exists():
            zip_path.unlink()
        logger.info("[VoskManager] Model extracted successfully.")

    safe_path = get_short_path(str(MODEL_PATH.resolve()))
    logger.info(f"[VoskManager] Loading Vosk model from safe path: {safe_path}...")
    return Model(safe_path)
