"""
pipeline/metadata_agent.py — Metadata Ajani

Zenginleştirilmiş Markdown belgesini okuyarak eksik YAML metadata
alanlarını doldurur ve belgenin başına yazar.

  title, category, created_date, source  → zaten var, dokunulmaz
  product, configuration_type, keywords  → regex (deterministik)
  topic, summary                         → Qwen via vLLM
"""

import re
import requests

from config import VLLM_URL, VLLM_MODEL


# ---------------------------------------------------------------------------
# vLLM çağrısı
# ---------------------------------------------------------------------------
def _vllm_call(prompt: str, max_tokens: int = 256) -> str:
    payload = {
        "model": VLLM_MODEL,
        "messages": [{"role": "user", "content": "/no_think\n" + prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "seed": 42,
    }
    try:
        r = requests.post(VLLM_URL, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"HATA: {e}"


# ---------------------------------------------------------------------------
# Deterministik alanlar
# ---------------------------------------------------------------------------
_PRODUCT_PATTERNS = [
    (r"Exchange",               "Microsoft Exchange Server"),
    (r"Active Directory|AD DS", "Active Directory"),
    (r"SharePoint",             "SharePoint"),
    (r"SQL Server",             "SQL Server"),
]

# Öncelik sırası kritik — ilk eşleşen kazanır
_CONFIG_TYPE_PATTERNS = [
    (r"dag|database availability",                "DAG Yapılandırma"),
    (r"healthcheck|health.check|saglik|sağlık",   "HealthCheck"),
    (r"kaldırma|kaldirma|uninstall|remove",        "Kaldırma"),
    (r"yedek|backup|restore|yedekleme",            "Yedekleme"),
    (r"ta[sş][ıi]ma|migrat|transfer|migrasyon",   "Migrasyon"),
    (r"performan|optimizasyon|tuning",             "Performans"),
    (r"kurulum|install|setup|deploy",              "Kurulum"),      # sertifika'dan ÖNCE
    (r"sertifika|certificate|cert",               "Sertifika"),
    (r"anonimle|anonymiz",                         "Anonimleştirme"),
    (r"yapilandirma|yapılandırma|configur",        "Yapılandırma"),
]

_CMDLET_PATTERN = re.compile(
    r'\b((?:Get|Set|New|Remove|Add|Enable|Disable|Install|Uninstall|'
    r'Move|Test|Start|Stop|Invoke|Resume|Suspend|Update|Import|Export|'
    r'Search|Write|Mount|Connect|Disconnect|Grant|Restore|Clear|Copy|'
    r'Register|Unregister|Reset|Repair|Backup|Merge|Split|Convert|'
    r'Publish|Unpublish|Request|Revoke|Send|Receive|Submit|Approve|'
    r'Deny|Lock|Unlock|Protect|Unprotect|Format|Measure|Select|Sort|'
    r'Group|Where|ForEach|Compare|Join|Expand)'
    r'-[A-Z][A-Za-z]+)\b'
)


def extract_product(text: str) -> str:
    for pattern, product in _PRODUCT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return product
    return "Microsoft Exchange Server"


def extract_configuration_type(text: str) -> str:
    for pattern, cfg_type in _CONFIG_TYPE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return cfg_type
    return "Yapılandırma"


def extract_keywords(text: str) -> list:
    cmdlets = list(dict.fromkeys(_CMDLET_PATTERN.findall(text)))
    return cmdlets[:15]


# ---------------------------------------------------------------------------
# Qwen tabanlı alanlar
# ---------------------------------------------------------------------------
_TOPIC_PROMPT = """Aşağıdaki teknik dokümanı oku ve konusunu TAM OLARAK 1 cümleyle özetle.
Sadece cümleyi yaz, başka hiçbir şey yazma.

DOKUMAN:
{text}"""

_SUMMARY_PROMPT = """Aşağıdaki teknik dokümanı oku ve 2-3 cümleyle özetle.
Teknik ekip için yazılmış, Exchange Server yönetimiyle ilgili.
Sadece özeti yaz, başka hiçbir şey yazma.

DOKUMAN:
{text}"""


def generate_topic(text: str) -> str:
    result = _vllm_call(_TOPIC_PROMPT.format(text=text[:3000]), max_tokens=100)
    return result if not result.startswith("HATA") else "Exchange Server yapılandırması"


def generate_summary(text: str) -> str:
    result = _vllm_call(_SUMMARY_PROMPT.format(text=text[:4000]), max_tokens=300)
    return result if not result.startswith("HATA") else ""


# ---------------------------------------------------------------------------
# YAML işlemleri
# ---------------------------------------------------------------------------
_YAML_BLOCK_RE = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)


def parse_existing_yaml(content: str) -> tuple:
    m = _YAML_BLOCK_RE.match(content)
    if not m:
        return {}, content
    try:
        import yaml
        data = yaml.safe_load(m.group(1)) or {}
    except Exception:
        data = {}
    body = content[m.end():]
    return data, body


def build_yaml_block(data: dict) -> str:
    lines = ["---"]
    for key, val in data.items():
        if isinstance(val, list):
            if not val:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f'  - "{item}"')
        elif isinstance(val, str) and '\n' in val:
            lines.append(f"{key}: |")
            for line in val.splitlines():
                lines.append(f"  {line}")
        else:
            safe = str(val).replace('"', '\\"')
            lines.append(f'{key}: "{safe}"')
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------
def generate_metadata(enriched_content: str) -> str:
    existing_yaml, body = parse_existing_yaml(enriched_content)

    existing_yaml["product"] = extract_product(body)
    existing_yaml["configuration_type"] = extract_configuration_type(
        existing_yaml.get("title", "") + " " + body
    )
    existing_yaml["keywords"] = extract_keywords(body)

    print("[Metadata] Konu üretiliyor...")
    existing_yaml["topic"] = generate_topic(body)
    print("[Metadata] Özet üretiliyor...")
    existing_yaml["summary"] = generate_summary(body)

    return build_yaml_block(existing_yaml) + body
