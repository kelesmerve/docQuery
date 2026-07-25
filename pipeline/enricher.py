"""
pipeline/enricher.py — Zenginleştirme Modülü

Görsel açıklamalarını ve gövde metnini zenginleştirir.
KOD KORUMA bu modülde YOKTUR — graph.py'deki
code_extractor_node / code_injector_node halleder.

  [x] Görsel yorumu: Qwen'e bağlam + görsel tipi ile çağrı
  [x] Gövde yapılandırma: Qwen ile Markdown formatı
  [x] IMG_PLACEHOLDER mekanizması (görsel referanslarını Qwen'den korur)
"""

import re
import os
import base64
from pipeline import model_http

from config import VLLM_URL, VLLM_MODEL


# ---------------------------------------------------------------------------
# Regex — cmdlet / prompt satırı tespiti (format_vision_output için)
# ---------------------------------------------------------------------------
_CMDLET_RE = re.compile(
    r'^((?:\[PS\]\s*)?(?:[A-Za-z]:\\[^\n>]*>)?\s*'
    r'(?:Get|Set|New|Remove|Add|Enable|Disable|Install|Uninstall|'
    r'Move|Test|Start|Stop|Invoke|Resume|Suspend|Update|Import|Export)'
    r'-[A-Za-z][\w-]*\b.*)',
    re.MULTILINE
)
_BULLET_CMD_RE = re.compile(
    r'^(\*\s+)((?:Get|Set|New|Remove|Add|Enable|Disable|Install|Uninstall|'
    r'Move|Test|Start|Stop|Invoke|Resume|Suspend|Update|Import|Export)'
    r'-[A-Za-z][^\n]+)$',
    re.MULTILINE
)
_PROMPT_LINE_RE = re.compile(r'^\[PS\]\s*[A-Za-z]:\\[^\n]*>', re.MULTILINE)
_CODE_BLOCK_RE  = re.compile(r'```[\s\S]*?```', re.DOTALL)


def _get_code_block_ranges(text: str) -> list:
    return [(m.start(), m.end()) for m in _CODE_BLOCK_RE.finditer(text)]


def _is_in_code_block(pos: int, ranges: list) -> bool:
    return any(s <= pos <= e for s, e in ranges)


# ---------------------------------------------------------------------------
# Bağlam çıkarma
# ---------------------------------------------------------------------------
def extract_context(markdown: str, img_path: str, chars: int = 500) -> str:
    pattern = re.escape(f'({img_path})')
    m = re.search(pattern, markdown)
    if not m:
        return ""
    start = max(0, m.start() - chars)
    snippet = markdown[start:m.start()].strip()
    snippet = re.sub(r'^---.*?---\n', '', snippet, flags=re.DOTALL)
    snippet = re.sub(r'^>.*?\n', '', snippet, flags=re.MULTILINE)
    return snippet.strip()[-chars:]


# ---------------------------------------------------------------------------
# vLLM çağrıları
# ---------------------------------------------------------------------------
def _call_enrichment_vllm(image_path: str, prompt: str) -> str:
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext  = image_path.rsplit(".", 1)[-1].lower()
        mime = f"image/{ext}" if ext in ("png", "jpg", "jpeg", "webp") else "image/png"
        payload = {
            "model": VLLM_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text",      "text": prompt}
            ]}],
            "temperature": 0, "seed": 42, "max_tokens": 800,
        }
        r = model_http.post(VLLM_URL, json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        if os.getenv('DOCQUERY_STRICT') == '1':
            raise
        return f"[Zenginlestirme hatasi: {e}]"


def _call_text_vllm(prompt: str, max_tokens: int = 1500) -> str:
    try:
        payload = {
            "model": VLLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "seed": 42, "max_tokens": max_tokens,
        }
        r = model_http.post(VLLM_URL, json=payload, timeout=180)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        if os.getenv('DOCQUERY_STRICT') == '1':
            raise
        print(f"[Yapilandirma] vLLM hatasi: {e}")
        return ""


# ---------------------------------------------------------------------------
# Zenginleştirme prompt'ları
# ---------------------------------------------------------------------------
_PROMPT_GUI = """/no_think
Bu ekran görüntüsü aşağıdaki Exchange Server teknik dokümanına aittir.

BAĞLAM (görselin ait olduğu adım):
{context}

Ekranı analiz et ve Türkçe olarak şu formatta yaz:

**[Pencere/Ekran Adı]:** (hangi pencere veya diyalog açık)
**[Yapılan İşlem]:** (bu adımda ne yapılıyor, tek cümle)
**[Teknik Detaylar]:**
- (önemli alanlar, değerler, liste öğeleri, checkbox durumları)

**[Sonuç]:** (bu adımın amacını ve sonucunu tek cümleyle açıkla)

Kısa ve teknik tut. Gereksiz açıklama yapma."""

_PROMPT_TERMINAL = """/no_think
Bu ekran görüntüsü aşağıdaki Exchange Server teknik dokümanına aittir.

BAĞLAM (görselin ait olduğu adım):
{context}

Ekrandaki PowerShell / terminal çıktısını analiz et ve Türkçe olarak şu formatta yaz:

**[Çalıştırılan Komut]:**
```powershell
(komutu buraya yaz)
```

**[Komut Çıktısı]:**
(çıktıyı olduğu gibi, tablo veya liste formatında yaz)

**[Sonuç]:** (komutun ne yaptığını ve sonucunu tek cümleyle açıkla)

Kısa ve teknik tut."""


def enrich_vision_output(image_path: str, img_type: str,
                         raw_vlm: str, context: str) -> str:
    prompt = (_PROMPT_TERMINAL if img_type == "terminal" else _PROMPT_GUI).format(
        context=context or "Exchange Server teknik dokumani"
    )
    from config import resolve_image_path
    real_path = resolve_image_path(image_path)
    result = _call_enrichment_vllm(real_path, prompt)
    if result.startswith("[Zenginlestirme hatasi"):
        return format_vision_output(raw_vlm)
    return result


# ---------------------------------------------------------------------------
# Fallback format
# ---------------------------------------------------------------------------
def format_vision_output(text: str) -> str:
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^Terminal output:?\s*$', line, re.IGNORECASE):
            result.append(line)
            i += 1
            block_lines = []
            while i < len(lines):
                if re.match(r'^(Window title|Controls|Buttons|Checkboxes):?\s*$',
                            lines[i], re.IGNORECASE):
                    break
                block_lines.append(lines[i])
                i += 1
            if block_lines:
                has_cmd = any(_CMDLET_RE.match(l) or _PROMPT_LINE_RE.match(l)
                              for l in block_lines if l.strip())
                lang = 'powershell' if has_cmd else 'text'
                result.append(f'```{lang}')
                result.extend(block_lines)
                result.append('```')
        else:
            result.append(line)
            i += 1
    return '\n'.join(result)


def format_body(text: str) -> str:
    ranges = _get_code_block_ranges(text)

    def replace_bullet_cmd(m):
        if _is_in_code_block(m.start(), ranges):
            return m.group(0)
        cmd = m.group(2).strip()
        return f'\n```powershell\n{cmd}\n```'

    return _BULLET_CMD_RE.sub(replace_bullet_cmd, text)


# ---------------------------------------------------------------------------
# Uyarı notu
# ---------------------------------------------------------------------------
WARNING_NOTE = (
    "> **Not:** Bu dokümandaki sunucu adları, domain ve kullanıcı bilgileri "
    "**örnek/kurgusal** değerlerdir. Gerçek ortamdaki değerlerle "
    "değiştirilmelidir.\n\n"
)


# ---------------------------------------------------------------------------
# Gövde yapılandırma prompt'u
# ---------------------------------------------------------------------------
_PROMPT_RESTRUCTURE = """/no_think
Aşağıdaki Exchange Server teknik dokümanın gövde metnini Markdown formatında yeniden yapılandır.

DOKÜMAN BAŞLIĞI: {title}

KURALLAR:
1. İçeriği KESINLIKLE değiştirme, sadece formatla ve düzenle
2. Belgenin tamamı için tek bir tutarlı başlık hiyerarşisi kur
3. Ana başlık için # kullan (DOKÜMAN BAŞLIĞI'nı kullan)
4. Bölümler için ## 1. ## 2. gibi numaralı başlıklar kullan
5. Alt başlıklar için ### 1.1. ### 1.2. kullan
6. Önemli uyarıları > **Not:** veya > **Öneri:** bloğuna al
7. Teknik terimleri, komut adlarını, dosya yollarını `backtick` ile işaretle
8. Bölümler arasına --- ayraç ekle
9. Madde listelerini - ile yaz
10. Görsel referansları {{IMG_PLACEHOLDER_N}} şeklinde işaretlenmiştir — onlara DOKUNMA
11. Uyarı notunu (> **Not:** ornek/kurgusal...) en üstte, başlıktan önce bırak
12. [[SECURE_CODE_BLOCK_N]] etiketlerine KESINLIKLE dokunma — olduğu gibi bırak
13. URL'LER: https:// ile başlayan URL'leri [text](url) formatına çevirme

YAPILANDIRILACAK METİN:
{body}

Sadece yapılandırılmış Markdown çıktısını ver. Açıklama ekleme."""


def restructure_body(content: str, use_restructure: bool = True) -> str:
    """Markdown gövde metnini Qwen ile yapılandırır.
    Kod blokları code_extractor_node tarafından zaten [[SECURE_CODE_BLOCK_N]]
    placeholder'larına dönüştürülmüş olmalıdır."""
    if not use_restructure:
        return content

    import yaml as _yaml
    yaml_match = re.match(r'^(---\n.*?\n---\n)', content, re.DOTALL)
    if yaml_match:
        yaml_block = yaml_match.group(1)
        body = content[yaml_match.end():]
        try:
            yaml_inner = re.sub(r'^---\s*', '', yaml_match.group(1).strip(),
                                flags=re.MULTILINE).strip()
            yaml_data = _yaml.safe_load(yaml_inner)
            title = (yaml_data.get('title', 'Teknik Dokuman')
                     if isinstance(yaml_data, dict) else 'Teknik Dokuman')
        except Exception:
            title = 'Teknik Dokuman'
    else:
        yaml_block, body, title = "", content, 'Teknik Dokuman'

    # Görsel referanslarını placeholder'a al
    img_pattern = re.compile(r'!\[.*?\]\([^)]+\)', re.MULTILINE)
    img_refs = img_pattern.findall(body)
    body_with_placeholders = body
    if img_refs:
        for i, img_ref in enumerate(img_refs):
            body_with_placeholders = body_with_placeholders.replace(
                img_ref, f'{{{{IMG_PLACEHOLDER_{i}}}}}', 1
            )

    # Çok kısa belgeler — Qwen'e gönderme
    if len(body.strip().splitlines()) < 5:
        return content

    MAX_BODY_CHARS = 8000
    if len(body_with_placeholders) > MAX_BODY_CHARS:
        if os.getenv('DOCQUERY_STRICT') == '1':
            raise ValueError('Belge model sınırını aşıyor; daha küçük bölümlere ayırın.')
        body_truncated = body_with_placeholders[:MAX_BODY_CHARS] + "\n[...]"
        print(f"[Yapilandirma] Govde {len(body_with_placeholders)} karakter, {MAX_BODY_CHARS}'e kisaltildi.")
    else:
        body_truncated = body_with_placeholders

    prompt = _PROMPT_RESTRUCTURE.replace("{title}", title).replace("{body}", body_truncated)
    restructured = _call_text_vllm(prompt, max_tokens=3000)

    if not restructured:
        print("[Yapilandirma] Qwen ciktisi bos, orijinal icerik korunuyor.")
        return content

    # Görsel referanslarını geri koy
    if img_refs:
        for i, img_ref in enumerate(img_refs):
            placeholder = f'{{{{IMG_PLACEHOLDER_{i}}}}}'
            if placeholder in restructured:
                restructured = restructured.replace(placeholder, img_ref, 1)
            else:
                restructured += f'\n\n{img_ref}\n'

    # Sahte placeholder'ları temizle
    restructured = re.sub(r'\{\{IMG_PLACEHOLDER_\d+\}\}', '', restructured)

    # Bozuk URL formatını düzelt
    _broken_url_re = re.compile(r'\[https?://\]\((https?://[^\)]+)\)[^\s\]"]*')
    restructured = _broken_url_re.sub(r'\1', restructured)

    print(f"[Yapilandirma] {len(img_refs)} gorsel referansi korundu.")
    return yaml_block + restructured + "\n"


# ---------------------------------------------------------------------------
# Ana zenginleştirme fonksiyonu
# ---------------------------------------------------------------------------
def enrich(markdown_content: str, vision_outputs: dict,
           validation_results: dict,
           use_enrichment: bool = True,
           anonymization_map: dict = None) -> str:
    """Zenginleştirilmiş Markdown içeriğini üretir.

    NOT: Kod blokları bu fonksiyon çağrılmadan ÖNCE graph.py'deki
    code_extractor_node tarafından [[SECURE_CODE_BLOCK_N]] placeholder'larına
    dönüştürülmüş olmalıdır. Bu fonksiyon kod koruma YAPMAZ.
    """
    from pipeline.anonymizer import apply_anonymization

    content = markdown_content

    if "ornek/kurgusal" not in content:
        content = re.sub(
            r'(---\n.*?\n---\n)', r'\1\n' + WARNING_NOTE,
            content, count=1, flags=re.DOTALL
        )

    content = format_body(content)

    for img_path, raw_vlm in vision_outputs.items():
        validation = validation_results.get(img_path, {})
        low_conf   = " [OCR dogrulamasi dusuk guven]" if validation.get('needs_review') else ""
        img_type   = validation.get('img_type', 'terminal')

        if use_enrichment:
            context     = extract_context(content, img_path)
            description = enrich_vision_output(img_path, img_type, raw_vlm, context)
            if anonymization_map:
                description = apply_anonymization(description, anonymization_map)
        else:
            description = format_vision_output(raw_vlm)

        pattern     = re.escape(f'({img_path})')
        replacement = (
            f'({img_path})\n\n'
            f'**Gorsel Aciklamasi:**{low_conf}\n'
            f'{description}\n'
        )
        content = re.sub(pattern, lambda _, r=replacement: r, content, count=1)

    if use_enrichment:
        content = restructure_body(content, use_restructure=True)

    return content
