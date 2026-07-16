"""
pipeline/pii_detector.py — Kişisel Bilgi (PII) Tespiti

Türkçe kişi isimlerini regex + Qwen ile tespit eder.
Qwen erişilemez durumdaysa regex fallback devreye girer.
"""

import re
import requests

from config import VLLM_URL, VLLM_MODEL


class PIIDetectionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Regex fallback — yaygın Türkçe ad kalıpları
# ---------------------------------------------------------------------------
_NAME_PATTERNS = [
    # "Kullanıcı: Ahmet Yılmaz" gibi etiketli kalıplar
    re.compile(
        r'(?:kullan[iı]c[iı]|admin|yönetici|yetkili|sorumlu)\s*:\s*'
        r'([A-ZÇĞİÖŞÜ][a-zçğışöüa-z]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğışöüa-z]+)+)',
        re.IGNORECASE
    ),
    # "tarafından: Ad Soyad"
    re.compile(
        r'taraf[iı]ndan\s*:\s*'
        r'([A-ZÇĞİÖŞÜ][a-zçğışöüa-z]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğışöüa-z]+)+)',
        re.IGNORECASE
    ),
]

_PROMPT_PII = """/no_think
Aşağıdaki metinde geçen gerçek kişi isimlerini listele.
Sadece isimleri yaz, her satıra bir isim.
Teknik terim, ürün adı veya hostname YAZMA.
İsim yoksa sadece "YOK" yaz.

METİN:
{text}"""


def _detect_via_regex(text: str) -> list:
    names = []
    for pat in _NAME_PATTERNS:
        for m in pat.finditer(text):
            name = m.group(1).strip()
            if name and name not in names:
                names.append(name)
    return names


def _detect_via_vllm(text: str) -> list:
    prompt = _PROMPT_PII.format(text=text[:3000])
    try:
        payload = {
            "model": VLLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "seed": 42,
            "max_tokens": 256,
        }
        r = requests.post(VLLM_URL, json=payload, timeout=30)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        if content.upper() == "YOK" or not content:
            return []
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        # Sadece 2+ kelimeli satırları isim say
        return [l for l in lines if len(l.split()) >= 2]
    except Exception as e:
        raise PIIDetectionError(f"vLLM PII tespiti basarisiz: {e}") from e


def detect_person_names(text: str) -> list:
    """Metindeki kişi isimlerini döner.
    vLLM erişilemezse regex fallback kullanır.

    Raises:
        PIIDetectionError: vLLM de regex de çalışmazsa
    """
    # Önce vLLM dene
    try:
        names = _detect_via_vllm(text)
        # vLLM'in kaçırdıklarını regex ile tamamla
        regex_names = _detect_via_regex(text)
        for n in regex_names:
            if n not in names:
                names.append(n)
        return names
    except PIIDetectionError:
        # Fallback: sadece regex
        names = _detect_via_regex(text)
        if names:
            return names
        # Her ikisi de başarısız
        raise PIIDetectionError("Hem vLLM hem regex PII tespiti basarisiz")
