"""
pipeline/anonymizer.py — Anonimleştirme Motoru

Tespit edilen varlıklar:
  - domains       : kartal.local, firma.com
  - netbios_domains: KARTAL\\user  → CONTOSO
  - hostnames     : EXC01, PRINTSRV → HOST01, FILESVC
  - databases     : MDB01, DB02, Mailbox Database 1 → DB01
  - person_names  : Ahmet Yılmaz → Kullanici01
  - emails        : ahmet@kartal.local → ahmet@contoso.com

Sözlük kalıcıdır (anonymization_dict.json). Aynı değer tüm belgeler
boyunca tutarlı kalır. Paralel worker sözlükleri merge_mappings() ile
first-write-wins + fuzzy match politikasıyla birleştirilir.
"""

import re
import json
import os
from difflib import get_close_matches, SequenceMatcher

DICT_PATH = "anonymization_dict.json"

_CATEGORIES = ["domains", "netbios_domains", "hostnames", "databases",
               "person_names", "emails"]

# ---------------------------------------------------------------------------
# Regex pattern'leri
# ---------------------------------------------------------------------------
DOMAIN_PATTERN         = r"\b([a-zA-Z0-9-]+\.(?:com|local|net|org))\b"
NETBIOS_PATTERN        = r"(?<![\\/:\w])([A-Z][A-Z0-9]{1,15})\\(?=[A-Za-z0-9])"
DATABASE_PREFIX_PATTERN = r"\b((?:MDB|DB)\d{1,3})\b"
DATABASE_NAMED_PATTERN  = r"(Mailbox Database \d+)"
EMAIL_PATTERN          = r"\b[\w.-]+@([a-zA-Z0-9-]+\.[a-zA-Z]{2,})\b"

# Rakamli:  EXC01, MBX03, APP1
# Rakamsiz: PRINTSRV, MAILSRV, FILESRV (bilinen sunucu son-ekleri)
HOSTNAME_PATTERN = (
    r"(?<![\\/.])\b("
    r"[A-Za-z]{2}[A-Za-z0-9]{0,10}\d{1,3}"
    r"|"
    r"[A-Za-z]{2,12}"
    r"(?:SRV|SVR|DC|FS|GW|MBX|HUB|CAS|DAG|WEB|SQL|APP|FTP|VPN|RDS|RDP)"
    r")\b"
)

# ---------------------------------------------------------------------------
# Stopword'ler — ürün/sürüm adları hostname sanılmasın
# ---------------------------------------------------------------------------
_HOSTNAME_STOPWORDS = {
    "windows10", "windows11", "windows2012", "windows2016", "windows2019", "windows2022",
    "office365", "office2013", "office2016", "office2019", "office2021",
    "exchange2013", "exchange2016", "exchange2019",
    "sql2016", "sql2017", "sql2019", "sql2022",
    "sharepoint2016", "sharepoint2019",
}
_HOSTNAME_STOPWORD_RE = re.compile(
    r"^(user|users|guest|test|windows|office|sql|sharepoint)\d+$", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Kurgusal değer havuzları
# ---------------------------------------------------------------------------
_FICTIONAL_DOMAINS = [
    "contoso.com", "fabrikam.com", "adventureworks.com",
    "northwind.com", "tailspin.com", "woodgrove.com",
    "alpineskihouse.com", "bellowscollege.com", "bestforyouorganics.com",
    "blueyonderairlines.com", "cohowinery.com", "consolidatedmessenger.com",
]
_FICTIONAL_NETBIOS = ["CONTOSO", "FABRIKAM", "ADVWORKS", "NORTHWIND", "TAILSPIN"]
_FICTIONAL_HOSTNAME_PREFIXES      = ["HOST", "NODE", "APP", "SRV", "MBX"]
_FICTIONAL_HOSTNAME_NOSUFFIX      = [
    "FILESVC", "PRINTSVC", "APPSVC", "MAILSVC", "NODESVC",
    "SRVA", "SRVB", "SRVC", "SRVD", "SRVE",
]
_DATABASE_PREFIXES = ("MDB", "DB")

# ---------------------------------------------------------------------------
# Fuzzy yardımcıları
# ---------------------------------------------------------------------------
_FUZZY_CUTOFF = 0.82


def normalize_key(value: str) -> str:
    return value.strip().lower()


def _is_fuzzy_equivalent(a: str, b: str) -> bool:
    na, nb = normalize_key(a), normalize_key(b)
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= _FUZZY_CUTOFF


# ---------------------------------------------------------------------------
# Sözlük yükleme / kaydetme
# ---------------------------------------------------------------------------
def empty_mapping() -> dict:
    return {cat: {} for cat in _CATEGORIES}


def load_dictionary() -> dict:
    if not os.path.exists(DICT_PATH):
        return empty_mapping()
    with open(DICT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    mapping = empty_mapping()
    for cat in _CATEGORIES:
        mapping[cat].update(data.get(cat, {}))
    if data.get("servers"):
        print("[Anonimlestirme] UYARI: Eski 'servers' kategorisi bulundu. Sozlugu sifirlayin.")
    return mapping


def save_dictionary(mapping: dict) -> None:
    with open(DICT_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Kurgusal değer üretme
# ---------------------------------------------------------------------------
def next_fictional_domain(index: int) -> str:
    return _FICTIONAL_DOMAINS[index % len(_FICTIONAL_DOMAINS)]


def next_fictional_netbios(index: int) -> str:
    return _FICTIONAL_NETBIOS[index % len(_FICTIONAL_NETBIOS)]


def next_fictional_hostname(original: str, mapping: dict):
    suffix_match = re.search(r"\d+$", original)
    used = set(mapping["hostnames"].values())
    original_lower = original.lower()

    if suffix_match:
        suffix = suffix_match.group()
        for prefix in _FICTIONAL_HOSTNAME_PREFIXES:
            cand = f"{prefix}{suffix}"
            if cand not in used and cand.lower() != original_lower:
                return cand
        idx = 0
        while True:
            cand = f"{_FICTIONAL_HOSTNAME_PREFIXES[idx % len(_FICTIONAL_HOSTNAME_PREFIXES)]}{suffix}_{idx}"
            if cand not in used and cand.lower() != original_lower:
                return cand
            idx += 1
    else:
        for cand in _FICTIONAL_HOSTNAME_NOSUFFIX:
            if cand not in used and cand.lower() != original_lower:
                return cand
        idx = 1
        while True:
            cand = f"SRVX{idx:03d}"
            if cand not in used and cand.lower() != original_lower:
                return cand
            idx += 1


def _db_family(original: str) -> str:
    up = original.upper()
    if up.startswith("MAILBOX DATABASE"):
        return "Mailbox Database"
    for p in _DATABASE_PREFIXES:
        if up.startswith(p):
            return p
    return "DB"


def next_fictional_database(original: str, mapping: dict, reserved: set = None) -> str:
    family = _db_family(original)
    used = set(mapping["databases"].values())
    reals = set(mapping["databases"].keys()) | (reserved or set())
    original_lower = original.lower()
    i = 1
    while True:
        cand = (f"Mailbox Database {i:010d}"
                if family == "Mailbox Database" else f"{family}{i:02d}")
        if cand not in used and cand not in reals and cand.lower() != original_lower:
            return cand
        i += 1


# ---------------------------------------------------------------------------
# Fuzzy eşleşme
# ---------------------------------------------------------------------------
def find_existing_match(original: str, existing_keys: list, cutoff: float = 0.85,
                        exact_only: bool = False):
    if not existing_keys:
        return None
    norm_original = normalize_key(original)
    norm_map = {normalize_key(k): k for k in existing_keys}
    if exact_only:
        return norm_map.get(norm_original)
    orig_suffix = re.search(r"\d+$", original)
    matches = get_close_matches(norm_original, list(norm_map.keys()), n=3, cutoff=cutoff)
    for match in matches:
        candidate = norm_map[match]
        cand_suffix = re.search(r"\d+$", candidate)
        if orig_suffix and cand_suffix and orig_suffix.group() != cand_suffix.group():
            continue
        return candidate
    return None


# ---------------------------------------------------------------------------
# Sözlük oluşturma / güncelleme
# ---------------------------------------------------------------------------
def build_or_update_dictionary(text: str, mapping: dict) -> dict:
    # --- Domain ---
    for m in re.finditer(DOMAIN_PATTERN, text):
        original = m.group(1)
        existing = find_existing_match(original, list(mapping["domains"].keys()))
        if existing:
            mapping["domains"][original] = mapping["domains"][existing]
        elif original not in mapping["domains"]:
            idx = len(set(mapping["domains"].values()))
            mapping["domains"][original] = next_fictional_domain(idx)

    # --- NetBIOS ---
    for m in re.finditer(NETBIOS_PATTERN, text):
        original = m.group(1)
        existing = find_existing_match(original, list(mapping["netbios_domains"].keys()))
        if existing:
            mapping["netbios_domains"][original] = mapping["netbios_domains"][existing]
        elif original not in mapping["netbios_domains"]:
            idx = len(set(mapping["netbios_domains"].values()))
            mapping["netbios_domains"][original] = next_fictional_netbios(idx)

    # --- Veritabanı ---
    db_found = [m.group(1) for m in re.finditer(DATABASE_NAMED_PATTERN, text, re.IGNORECASE)]
    db_found += [m.group(1) for m in re.finditer(DATABASE_PREFIX_PATTERN, text, re.IGNORECASE)]
    _DB_MEANINGLESS = {'DB0', 'MDB0', 'DB00', 'MDB00', 'db0', 'mdb0', 'db00', 'mdb00'}
    db_found = [d for d in db_found if d not in _DB_MEANINGLESS]
    _literal_re = re.compile(r'"[^"]*"')
    _literals = set()
    for lm in _literal_re.finditer(text):
        for dm in re.finditer(DATABASE_PREFIX_PATTERN, lm.group(), re.IGNORECASE):
            _literals.add(dm.group(1).upper())
    _text_no_literals = _literal_re.sub(' ', text)
    _independent = {
        dm.group(1).upper()
        for dm in re.finditer(DATABASE_PREFIX_PATTERN, _text_no_literals, re.IGNORECASE)
    }
    db_found = [d for d in db_found if d.upper() not in _literals or d.upper() in _independent]
    pre_reserved = set(mapping.get("_db_pre_reserved") or [])
    db_reserved = set(mapping["databases"].keys()) | set(db_found) | pre_reserved
    for original in db_found:
        existing = find_existing_match(original, list(mapping["databases"].keys()), exact_only=True)
        if existing:
            mapping["databases"][original] = mapping["databases"][existing]
        elif original not in mapping["databases"]:
            mapping["databases"][original] = next_fictional_database(
                original, mapping, reserved=db_reserved)

    # --- Hostname ---
    db_keys_lower = {k.lower() for k in mapping["databases"]}
    nb_keys_lower = {k.lower() for k in mapping["netbios_domains"]}
    for m in re.finditer(HOSTNAME_PATTERN, text, re.IGNORECASE):
        original = m.group(1)
        low = original.lower()
        _is_db_prefix = re.match(r'^(?:MDB|DB)\d*$', original, re.IGNORECASE)
        if (low in _HOSTNAME_STOPWORDS
                or _HOSTNAME_STOPWORD_RE.match(original)
                or low in db_keys_lower
                or low in nb_keys_lower
                or _is_db_prefix):
            continue
        existing = find_existing_match(original, list(mapping["hostnames"].keys()), exact_only=True)
        if existing:
            mapping["hostnames"][original] = mapping["hostnames"][existing]
        elif original not in mapping["hostnames"]:
            fictional = next_fictional_hostname(original, mapping)
            if fictional:
                mapping["hostnames"][original] = fictional

    # --- Email ---
    for m in re.finditer(EMAIL_PATTERN, text):
        full_email = m.group(0)
        domain_part = m.group(1)
        existing = find_existing_match(full_email, list(mapping["emails"].keys()))
        if existing:
            mapping["emails"][full_email] = mapping["emails"][existing]
        elif full_email not in mapping["emails"]:
            domain_existing = find_existing_match(domain_part, list(mapping["domains"].keys()))
            if domain_existing:
                fictional_domain = mapping["domains"][domain_existing]
            else:
                idx = len(set(mapping["domains"].values()))
                fictional_domain = next_fictional_domain(idx)
                mapping["domains"][domain_part] = fictional_domain
            local_part = full_email.split("@")[0]
            mapping["emails"][full_email] = f"{local_part}@{fictional_domain}"

    return mapping


# ---------------------------------------------------------------------------
# Kişi ismi kayıt
# ---------------------------------------------------------------------------
def register_person_names(names: list, mapping: dict) -> dict:
    for name in names:
        name = name.strip()
        if not name:
            continue
        existing = find_existing_match(name, list(mapping["person_names"].keys()))
        if existing:
            mapping["person_names"][name] = mapping["person_names"][existing]
        elif name not in mapping["person_names"]:
            idx = len(set(mapping["person_names"].values())) + 1
            mapping["person_names"][name] = f"Kullanici{idx:02d}"
    return mapping


# ---------------------------------------------------------------------------
# Uygulama
# ---------------------------------------------------------------------------
_CS_CATS = ["emails", "domains", "netbios_domains"]
_CI_CATS = ["hostnames", "databases", "person_names"]


def _apply_group(text: str, replacements: dict, ignore_case: bool) -> str:
    if not replacements:
        return text
    keys = sorted(replacements.keys(), key=len, reverse=True)
    flags = re.IGNORECASE if ignore_case else 0
    pattern = re.compile("|".join(re.escape(k) for k in keys), flags)
    if ignore_case:
        lower_map = {k.lower(): v for k, v in replacements.items()}
        return pattern.sub(lambda mo: lower_map[mo.group(0).lower()], text)
    return pattern.sub(lambda mo: replacements[mo.group(0)], text)


def apply_anonymization(text: str, mapping: dict) -> str:
    cs = {}
    for c in _CS_CATS:
        cs.update(mapping[c])
    text = _apply_group(text, cs, ignore_case=False)
    ci = {}
    for c in _CI_CATS:
        ci.update(mapping[c])
    text = _apply_group(text, ci, ignore_case=True)
    return text


# ---------------------------------------------------------------------------
# Paralel worker merge
# ---------------------------------------------------------------------------
def merge_mappings(global_mapping: dict, worker_mapping: dict) -> list:
    """Paralel worker sözlüğünü global'e merge eder.
    Strateji: first-write-wins + fuzzy match.
    Dönüş: uyarı listesi (qa_issues'a eklenir).
    """
    warnings = []

    for category in _CATEGORIES:
        global_cat = global_mapping[category]
        worker_cat = worker_mapping.get(category, {})
        reverse_global = {v: k for k, v in global_cat.items()}

        for original, fictional in worker_cat.items():
            # Adım 1: Fuzzy ile global'de var mı?
            existing_key = next(
                (gk for gk in global_cat if _is_fuzzy_equivalent(gk, original)),
                None
            )
            if existing_key is not None:
                existing_fictional = global_cat[existing_key]
                if not _is_fuzzy_equivalent(existing_fictional, fictional):
                    warnings.append(
                        f"[{category}] MERGE CAKISMA: '{original}' "
                        f"global='{existing_fictional}' worker='{fictional}' → global korundu"
                    )
                global_cat[original] = existing_fictional
                continue

            # Adım 2: fictional başkasına atanmış mı?
            if fictional in reverse_global:
                existing_original = reverse_global[fictional]
                if not _is_fuzzy_equivalent(existing_original, original):
                    warnings.append(
                        f"[{category}] FICTIONAL CAKISMA: '{fictional}' zaten "
                        f"'{existing_original}' icin kullaniliyor → '{original}' icin yeni atama"
                    )
                    if category == "netbios_domains":
                        used = set(global_cat.values())
                        i = 0
                        new_f = next_fictional_netbios(len(used))
                        while new_f in used:
                            i += 1
                            new_f = next_fictional_netbios(len(used) + i)
                        global_cat[original] = new_f
                        reverse_global[new_f] = original
                    else:
                        global_cat[original] = fictional
                        reverse_global[fictional] = original
                else:
                    global_cat[original] = fictional
            else:
                # Adım 3: Temiz — doğrudan ekle
                global_cat[original] = fictional
                reverse_global[fictional] = original

    return warnings


# ---------------------------------------------------------------------------
# Tutarlılık kontrolü
# ---------------------------------------------------------------------------
def check_anonymization_consistency(mapping: dict) -> list:
    issues = []
    for category in _CATEGORIES:
        reverse_map = {}
        for original, fictional in mapping[category].items():
            if fictional in reverse_map:
                existing = reverse_map[fictional]
                if not _is_fuzzy_equivalent(existing, original):
                    issues.append(
                        f"[{category}] CAKISMA: '{fictional}' hem '{existing}' "
                        f"hem '{original}' icin kullanilmis"
                    )
            else:
                reverse_map[fictional] = original
    return issues
