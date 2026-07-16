"""
pipeline/image_classifier.py — Görsel Tip Sınıflandırıcı

VLM çıktısındaki anahtar kelimelere bakarak görselin
GUI (dialog/form) mi yoksa terminal (PowerShell/cmd) çıktısı mı
olduğunu belirler.
"""

import re

_TERMINAL_SIGNALS = [
    r"terminal output",
    r"powershell",
    r"\[ps\]",
    r"cmdlet",
    r"get-\w+",
    r"set-\w+",
    r"new-\w+",
    r"c:\\",
    r"\$\w+",
    r"true|false",          # PS bool çıktıları
    r"\|\s*\w+",            # pipe
]

_TERMINAL_RE = re.compile(
    "|".join(_TERMINAL_SIGNALS), re.IGNORECASE
)


def classify_image_type(vlm_text: str) -> str:
    """VLM metninden görsel tipini belirler.

    Returns:
        "terminal" — PowerShell / komut satırı çıktısı
        "gui"      — GUI dialog, form, Exchange admin ekranı
    """
    if not vlm_text or vlm_text.startswith("HATA"):
        return "gui"

    hits = len(_TERMINAL_RE.findall(vlm_text))
    return "terminal" if hits >= 2 else "gui"
