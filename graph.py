"""
graph.py — LangGraph Ana Orkestratör

Akış:
  trigger
    → vision_validation_worker (paralel, Send API)
    → anonymize
    → code_extractor        ← YENİ: kod bloklarını [[SECURE_CODE_BLOCK_N]]'e çevirir
    → enrich                ← Qwen hiç kod görmez
    → code_injector         ← YENİ: placeholder'ları geri koyar
    → [metadata || qa]      (paralel)
    → finalize
    → END
"""

import re
import os
import base64
from pipeline import model_http
import operator
from typing import Annotated

from langgraph.graph import StateGraph, END
from langgraph.types import Send
from typing import TypedDict

from config import resolve_image_path, OUTPUT_APPROVED_DIR, OUTPUT_REVIEW_DIR
from pipeline.anonymizer import (
    load_dictionary, save_dictionary, build_or_update_dictionary,
    apply_anonymization, check_anonymization_consistency,
    register_person_names, empty_mapping, merge_mappings,
    DATABASE_PREFIX_PATTERN, DATABASE_NAMED_PATTERN,
)
from pipeline.pii_detector import detect_person_names, PIIDetectionError
from pipeline.image_classifier import classify_image_type
from pipeline.ocr_validator import validate_with_ocr
from pipeline.qa import collect_qa_issues
from pipeline.metadata_agent import generate_metadata
from pipeline.enricher import enrich
from config import VLLM_URL, VLLM_MODEL

# ---------------------------------------------------------------------------
# Vision prompt
# ---------------------------------------------------------------------------
VISION_PROMPT = (
    "Extract ALL visible text exactly as shown, including any sidebar, tree view, "
    "navigation panel, or list items - not just the main dialog. Scan the entire image "
    "from left to right, top to bottom, and do not skip any region.\n"
    "Then list:\n"
    "- Window title\n"
    "- Controls\n"
    "- Buttons\n"
    "- Checkboxes\n"
    "- Terminal output\n\n"
    "Do not explain.\n"
    "Return only the extracted information."
)

_PLACEHOLDER_PREFIX = "SECURE_CODE_BLOCK"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class ImageState(TypedDict):
    image_path: str


class PipelineState(TypedDict):
    markdown_path:    str
    markdown_content: str
    original_markdown: str
    image_refs:       list
    vision_outputs:   Annotated[dict, operator.ior]
    validation_results: Annotated[dict, operator.ior]
    anonymization_map: dict
    qa_issues:        Annotated[list, operator.add]
    enriched_content: str
    metadata_yaml:    dict
    extracted_codes:  dict   # code_extractor ↔ code_injector


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def call_vision_vllm(image_path: str) -> str:
    img_b64 = image_to_base64(image_path)
    ext  = image_path.rsplit(".", 1)[-1].lower()
    mime = f"image/{ext}" if ext in ("png", "jpg", "jpeg", "webp") else "image/png"
    payload = {
        "model": VLLM_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            {"type": "text",      "text": VISION_PROMPT},
        ]}],
        "temperature": 0.1, "seed": 42, "max_tokens": 2048,
    }
    r = model_http.post(VLLM_URL, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Node 1 — Tetikleme
# ---------------------------------------------------------------------------
def trigger_node(state: PipelineState) -> dict:
    with open(state['markdown_path'], 'r', encoding='utf-8') as f:
        content = f.read()
    all_refs = re.findall(r'!\[.*?\]\((.*?)\)', content)

    valid_refs, missing = [], []
    for ref in all_refs:
        real_path = resolve_image_path(ref)
        if os.path.exists(real_path):
            valid_refs.append(ref)
        else:
            missing.append(ref)
            print(f"[Tetikleme] UYARI: Gorsel bulunamadi: {real_path}")

    parser_issues = [
        f"[PARSER] Eksik gorsel dosyasi: {ref} -> {resolve_image_path(ref)}"
        for ref in missing
    ]
    print(f"[Tetikleme] Bulunan gorsel: {len(valid_refs)}, Eksik: {len(missing)}")
    return {
        "markdown_content":  content,
        "original_markdown": content,
        "image_refs":        valid_refs,
        "qa_issues":         parser_issues,
    }


# ---------------------------------------------------------------------------
# Node 2 — Vision + Validation (paralel worker)
# ---------------------------------------------------------------------------
def vision_validation_worker(state: ImageState) -> dict:
    image_path     = state["image_path"]
    real_img_path  = resolve_image_path(image_path)

    print(f'[Vision] Isleniyor: {real_img_path}')
    try:
        vlm_text = call_vision_vllm(real_img_path)
    except Exception as e:
        if os.getenv('DOCQUERY_STRICT') == '1':
            raise
        vlm_text = f'HATA: {e}'

    print(f'[Dogrulama] Isleniyor: {real_img_path}')
    img_type   = classify_image_type(vlm_text)
    validation = validate_with_ocr(real_img_path, img_type, vlm_text)

    flag = "INCELEME GEREKIYOR" if validation['needs_review'] else "Onaylandi"
    print(f"  Tur: {img_type}, Motor: {validation['engine_used']}, "
          f"Benzerlik: {validation['similarity_score']:.2f} - {flag}")

    return {
        "vision_outputs":     {image_path: vlm_text},
        "validation_results": {image_path: validation},
    }


# ---------------------------------------------------------------------------
# Node 3 — Anonimleştirme
# ---------------------------------------------------------------------------
def anonymize_node(state: PipelineState) -> dict:
    print("[Anonimlestirme] Sozluk yukleniyor...")
    mapping = load_dictionary()

    # DB pre-reservation
    all_texts   = [state['markdown_content']] + list(state['vision_outputs'].values())
    pre_reserved = set(mapping["databases"].keys())
    for t in all_texts:
        pre_reserved.update(m.group(1) for m in re.finditer(DATABASE_NAMED_PATTERN, t))
        pre_reserved.update(m.group(1) for m in re.finditer(DATABASE_PREFIX_PATTERN, t, re.IGNORECASE))
    mapping["_db_pre_reserved"] = list(pre_reserved)

    # Ana doküman
    mapping = build_or_update_dictionary(state['markdown_content'], mapping)

    new_issues = []

    # Paralel worker'lar — her görsel ayrı worker_map
    for img_path, vlm_text in state['vision_outputs'].items():
        worker_map = empty_mapping()
        worker_map["_db_pre_reserved"] = mapping.get("_db_pre_reserved", [])
        worker_map = build_or_update_dictionary(vlm_text, worker_map)
        worker_map.pop("_db_pre_reserved", None)

        # VALIDATION GATE: VLM hallüsinasyon filtresi
        markdown = state['markdown_content']
        rejected = []
        for category in ["domains", "netbios_domains", "hostnames", "databases", "emails"]:
            confirmed = {}
            for original, fictional in worker_map[category].items():
                if re.search(re.escape(original), markdown, re.IGNORECASE):
                    confirmed[original] = fictional
                else:
                    rejected.append(
                        f"[{category}] '{original}' markdown'da yok → reddedildi (halusinasyon?)"
                    )
            worker_map[category] = confirmed

        if rejected:
            new_issues.extend([f"[{img_path}] [GATE] {r}" for r in rejected])

        warnings = merge_mappings(mapping, worker_map)
        if warnings:
            new_issues.extend([f"[{img_path}] {w}" for w in warnings])

    mapping.pop("_db_pre_reserved", None)

    # Kişi ismi tespiti
    texts = [state['markdown_content']] + list(state['vision_outputs'].values())
    for t in texts:
        try:
            names  = detect_person_names(t)
            mapping = register_person_names(names, mapping)
        except PIIDetectionError as e:
            if os.getenv('DOCQUERY_STRICT') == '1':
                raise
            new_issues.append(f"[PII] Kisi ismi tespiti basarisiz: {e}")

    # Uygula
    anon_markdown     = apply_anonymization(state['markdown_content'], mapping)
    anonymized_vision = {
        img_path: apply_anonymization(vlm_text, mapping)
        for img_path, vlm_text in state['vision_outputs'].items()
    }

    new_issues.extend(check_anonymization_consistency(mapping))

    if new_issues:
        print("[Anonimlestirme] UYARI: Sorunlar tespit edildi:")
        for issue in new_issues:
            print(f"    - {issue}")

    save_dictionary(mapping)
    total = sum(len(mapping[c]) for c in
                ["domains", "netbios_domains", "hostnames", "databases", "person_names", "emails"])
    print(f"[Anonimlestirme] Toplam {total} varlik anonimlestirildi.")

    return {
        "markdown_content":  anon_markdown,
        "vision_outputs":    anonymized_vision,
        "anonymization_map": mapping,
        "qa_issues":         new_issues,
    }


# ---------------------------------------------------------------------------
# Node 4 — Kod Çıkarıcı (YENİ)
# ---------------------------------------------------------------------------
def code_extractor_node(state: PipelineState) -> dict:
    """Markdown'daki kod bloklarını, backtick'leri, PS satırlarını ve
    URL'leri çıkarır, yerlerine [[SECURE_CODE_BLOCK_N]] placeholder koyar.
    Qwen hiçbir zaman kod görmez."""
    content = state['markdown_content']
    codes   = {}
    idx     = [0]

    def _protect(m):
        key        = f"[[{_PLACEHOLDER_PREFIX}_{idx[0]}]]"
        codes[key] = m.group(0)
        idx[0]    += 1
        return key

    _img      = re.compile(r'!\[.*?\]\([^)]+\)')
    _fenced   = re.compile(r'```[\s\S]*?```', re.MULTILINE)
    _backtick = re.compile(r'`[^`\n]+`')
    _ps_line  = re.compile(r'^[ \t]*\$[A-Za-z].*$', re.MULTILINE)
    _url      = re.compile(r'https?://[^\s\)\]"]+')

    out = _img.sub(_protect, content)
    out = _fenced.sub(_protect, out)
    out = _backtick.sub(_protect, out)
    out = _ps_line.sub(_protect, out)
    out = _url.sub(_protect, out)

    print(f"[KodCoruyucu] {len(codes)} blok cikarildi.")
    return {
        "markdown_content": out,
        "extracted_codes":  codes,
    }


# ---------------------------------------------------------------------------
# Node 5 — Zenginleştirme
# ---------------------------------------------------------------------------
def enrich_node(state: PipelineState) -> dict:
    print("[Zenginlestirme] Gorsel yorumlari uretiliyor...")
    content = state['markdown_content']
    codes = dict(state.get('extracted_codes') or {})
    # Enricher needs image references to attach descriptions; it protects them
    # itself during restructuring. Executable code remains hidden from the model.
    for key, value in list(codes.items()):
        if re.fullmatch(r'!\[.*?\]\([^)]+\)', value):
            content = content.replace(key, value)
            del codes[key]
    enriched = enrich(
        content,
        state['vision_outputs'],
        state['validation_results'],
        use_enrichment=True,
        anonymization_map=state.get('anonymization_map'),
    )
    print("[Zenginlestirme] Tamamlandi.")
    return {"enriched_content": enriched, "extracted_codes": codes}


# ---------------------------------------------------------------------------
# Node 6 — Kod Enjektörü (YENİ)
# ---------------------------------------------------------------------------
def code_injector_node(state: PipelineState) -> dict:
    """Qwen'in yapılandırdığı metne orijinal kod bloklarını geri yerleştirir."""
    content = state['enriched_content']
    codes   = state.get('extracted_codes') or {}
    missing = [key for key in codes if key not in content]

    for key, original in codes.items():
        content = content.replace(key, original)

    lost = len(re.findall(r'\[\[SECURE_CODE_BLOCK_\d+\]\]', content))
    if lost:
        print(f"[KodInjector] UYARI: {lost} placeholder Qwen tarafindan kaybedildi, temizlendi.")
    content = re.sub(r'\[\[SECURE_CODE_BLOCK_\d+\]\]', '', content)

    print(f"[KodInjector] {len(codes) - len(missing)} blok geri yuklendi.")
    return {"enriched_content": content,
            "qa_issues": [f"[KOD] {len(missing)} korunan blok model çıktısında kayboldu."] if missing else []}


# ---------------------------------------------------------------------------
# Node 7 — Metadata
# ---------------------------------------------------------------------------
def metadata_node(state: PipelineState) -> dict:
    print("[Metadata] Uretiliyor...")
    updated = generate_metadata(state['enriched_content'])
    print("[Metadata] Tamamlandi.")
    return {"enriched_content": updated}


# ---------------------------------------------------------------------------
# Node 8 — QA
# ---------------------------------------------------------------------------
def qa_node(state: PipelineState) -> dict:
    new_issues = collect_qa_issues(state, existing_issues=None)
    all_issues = list(state.get("qa_issues") or []) + new_issues
    if all_issues:
        print(f"[QA] {len(all_issues)} sorun tespit edildi:")
        for i in all_issues:
            print(f"    - {i}")
    else:
        print("[QA] Tum kontroller gecti.")
    return {"qa_issues": new_issues}


# ---------------------------------------------------------------------------
# Node 9 — Finalize (join noktası)
# ---------------------------------------------------------------------------
def finalize_node(state: PipelineState) -> dict:
    return {}


# ---------------------------------------------------------------------------
# Dinamik yönlendirici
# ---------------------------------------------------------------------------
def route_images(state: PipelineState):
    if not state.get("image_refs"):
        return "anonymize"
    return [Send("vision_validation_worker", {"image_path": img})
            for img in state["image_refs"]]


# ---------------------------------------------------------------------------
# Graph kurulumu
# ---------------------------------------------------------------------------
graph = StateGraph(PipelineState)

graph.add_node("trigger",                  trigger_node)
graph.add_node("vision_validation_worker", vision_validation_worker)
graph.add_node("anonymize",                anonymize_node)
graph.add_node("code_extractor",           code_extractor_node)
graph.add_node("enrich",                   enrich_node)
graph.add_node("code_injector",            code_injector_node)
graph.add_node("metadata",                 metadata_node)
graph.add_node("qa",                       qa_node)
graph.add_node("finalize",                 finalize_node)

graph.set_entry_point("trigger")

# 1. Paralel vision
graph.add_conditional_edges(
    "trigger",
    route_images,
    {
        "vision_validation_worker": "vision_validation_worker",
        "anonymize": "anonymize",
    }
)
graph.add_edge("vision_validation_worker", "anonymize")

# 2. Sıralı zincir
graph.add_edge("anonymize",      "code_extractor")
graph.add_edge("code_extractor", "enrich")
graph.add_edge("enrich",         "code_injector")

# 3. Paralel metadata + qa
graph.add_edge("code_injector", "metadata")
graph.add_edge("code_injector", "qa")

# 4. Join
graph.add_edge("metadata",  "finalize")
graph.add_edge("qa",        "finalize")
graph.add_edge("finalize",  END)

app = graph.compile()


# ---------------------------------------------------------------------------
# Tekli çalıştırma
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    initial_state = {
        "markdown_path":    "test_input/test.md",
        "markdown_content": "",
        "original_markdown": "",
        "image_refs":       [],
        "vision_outputs":   {},
        "validation_results": {},
        "anonymization_map": {},
        "qa_issues":        [],
        "enriched_content": "",
        "metadata_yaml":    {},
        "extracted_codes":  {},
    }

    result = app.invoke(initial_state)

    input_filename = os.path.splitext(os.path.basename(initial_state["markdown_path"]))[0]
    output_filename = f"{input_filename}.md"

    qa_issues  = result.get('qa_issues', [])
    output_dir = OUTPUT_REVIEW_DIR if qa_issues else OUTPUT_APPROVED_DIR
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result["enriched_content"])

    if qa_issues:
        print(f"\n[!] MANUEL INCELEME GEREKIYOR. Cikti: {output_path}")
        for issue in qa_issues:
            print(f"   - {issue}")
    else:
        print(f"\n[OK] Onaylandi. Cikti: {output_path}")
