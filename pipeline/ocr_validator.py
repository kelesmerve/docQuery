"""
pipeline/ocr_validator.py — OCR Doğrulama

VLM çıktısını Tesseract (önce) veya EasyOCR (fallback) ile
karşılaştırarak benzerlik skoru üretir.
Düşük skor → needs_review = True.
"""

import re
from difflib import SequenceMatcher

try:
    import pytesseract
    from PIL import Image
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

try:
    import easyocr
    _EASYOCR_OK = True
    _easyocr_reader = None  # lazy init
except ImportError:
    _EASYOCR_OK = False

from config import OCR_CONFIDENCE_THRESHOLD


def _normalize(text: str) -> str:
    """Karşılaştırma için metni normalize et."""
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()


def _similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _ocr_tesseract(image_path: str) -> tuple:
    """(metin, güven) döner."""
    try:
        img = Image.open(image_path)
        data = pytesseract.image_to_data(img, lang="tur+eng",
                                         output_type=pytesseract.Output.DICT)
        words = [w for w, c in zip(data["text"], data["conf"])
                 if w.strip() and int(c) > 0]
        confs = [int(c) for c in data["conf"] if int(c) > 0]
        text = " ".join(words)
        avg_conf = sum(confs) / len(confs) / 100 if confs else 0.0
        return text, avg_conf
    except Exception as e:
        return "", 0.0


def _ocr_easyocr(image_path: str) -> tuple:
    """(metin, güven) döner."""
    global _easyocr_reader
    try:
        if _easyocr_reader is None:
            _easyocr_reader = easyocr.Reader(["tr", "en"], gpu=False)
        results = _easyocr_reader.readtext(image_path)
        words = [r[1] for r in results]
        confs = [r[2] for r in results]
        text = " ".join(words)
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return text, avg_conf
    except Exception as e:
        return "", 0.0


def validate_with_ocr(image_path: str, img_type: str, vlm_text: str) -> dict:
    """VLM çıktısını OCR ile doğrular.

    Returns dict:
        engine_used     : "tesseract" | "easyocr" | "none"
        ocr_text        : str
        ocr_confidence  : float  (0-1)
        similarity_score: float  (0-1)
        needs_review    : bool
        img_type        : str
    """
    result = {
        "engine_used": "none",
        "ocr_text": "",
        "ocr_confidence": 0.0,
        "similarity_score": 1.0,
        "needs_review": False,
        "img_type": img_type,
    }

    if not image_path or vlm_text.startswith("HATA"):
        result["needs_review"] = True
        return result

    ocr_text, confidence = "", 0.0

    if _TESSERACT_OK:
        ocr_text, confidence = _ocr_tesseract(image_path)
        result["engine_used"] = "tesseract"
    elif _EASYOCR_OK:
        ocr_text, confidence = _ocr_easyocr(image_path)
        result["engine_used"] = "easyocr"
    else:
        # OCR mevcut değil — skoru nötr bırak
        result["needs_review"] = False
        return result

    sim = _similarity(vlm_text, ocr_text)
    result["ocr_text"]         = ocr_text
    result["ocr_confidence"]   = round(confidence, 2)
    result["similarity_score"] = round(sim, 2)

    # Düşük güven VEYA düşük benzerlik → inceleme
    result["needs_review"] = (
        confidence < OCR_CONFIDENCE_THRESHOLD or
        (confidence > 0 and sim < 0.3)
    )
    return result
