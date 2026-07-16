"""
pipeline/qa.py — Kalite Kontrol

enriched_content üzerinde şu kontrolleri yapar:
  1. OCR güven skoru düşük görseller
  2. Eksik görsel açıklaması
  3. PII sızıntısı (gerçek isim kaldı mı?)
  4. Gövde çok kısa mı?
"""

import re


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def _count_images(content: str) -> int:
    return len(re.findall(r'!\[.*?\]\([^)]+\)', content))


def _count_descriptions(content: str) -> int:
    return len(re.findall(r'\*\*Gorsel Aciklamasi:\*\*', content))


def _body_line_count(content: str) -> int:
    yaml_end = re.search(r'^---\n.*?\n---\n', content, re.DOTALL)
    body = content[yaml_end.end():] if yaml_end else content
    return len([l for l in body.splitlines() if l.strip()])


# ---------------------------------------------------------------------------
# Ana kontrol fonksiyonu
# ---------------------------------------------------------------------------
def collect_qa_issues(state: dict, existing_issues=None) -> list:
    """State'i inceleyerek yeni QA sorunlarını döner.

    Parametreler:
        state           : PipelineState
        existing_issues : önceki aşamalardan gelen sorunlar (kullanılmaz,
                          sadece imza uyumu için)
    """
    issues = []
    content      = state.get("enriched_content") or state.get("markdown_content", "")
    val_results  = state.get("validation_results", {})
    anon_map     = state.get("anonymization_map", {})

    # --- 1. OCR güven skoru ---
    for img_path, val in val_results.items():
        conf = val.get("ocr_confidence", 1.0)
        if val.get("needs_review") and conf < 0.5:
            issues.append(
                f"[OCR] Dusuk guven ({conf:.2f}) - gorsel okumasi supheli: {img_path}"
            )

    # --- 2. Eksik görsel açıklaması ---
    img_count  = _count_images(content)
    desc_count = _count_descriptions(content)
    if img_count > 0 and desc_count < img_count:
        issues.append(
            f"[GORSEL] {img_count} gorsel var, {desc_count} aciklama var "
            f"- {img_count - desc_count} eksik"
        )

    # --- 3. Gövde çok kısa ---
    line_count = _body_line_count(content)
    if line_count < 5:
        issues.append(
            f"[GOVDE] Kaynak belge bos veya cok kisa ({line_count} satir)"
        )

    # --- 4. PII sızıntısı — kişi adları hâlâ metinde mi? ---
    person_map = anon_map.get("person_names", {})
    for real_name in person_map:
        if real_name in content:
            issues.append(
                f"[PII] Gercek kisi adi metinde kaldi: '{real_name}'"
            )

    return issues
