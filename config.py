"""
config.py — Proje genelinde sabitler ve yol çözümleme
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ---------------------------------------------------------------------------
# Dizinler
# ---------------------------------------------------------------------------
BASE_DIR             = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR            = os.path.join(BASE_DIR, "test_input")
IMAGE_DIR            = os.path.join(BASE_DIR, "test-images")
OUTPUT_DIR           = os.path.join(BASE_DIR, "results")
OUTPUT_APPROVED_DIR  = os.path.join(OUTPUT_DIR, "approved")
OUTPUT_REVIEW_DIR    = os.path.join(OUTPUT_DIR, "needs_review")

# ---------------------------------------------------------------------------
# vLLM
# ---------------------------------------------------------------------------
VLLM_URL   = os.getenv("VLLM_URL",   "http://localhost:8001/v1/chat/completions")
VLLM_MODEL = os.getenv("VLLM_MODEL", "qwen3-vl-30b-a3b")

# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
OCR_CONFIDENCE_THRESHOLD = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "0.5"))

# ---------------------------------------------------------------------------
# Yol çözümleme
# ---------------------------------------------------------------------------
def resolve_image_path(ref: str) -> str:
    """Markdown'daki görsel referansını (images/foo.png) gerçek dosya yoluna çevirir."""
    filename = os.path.basename(ref)
    return os.path.join(IMAGE_DIR, filename)
