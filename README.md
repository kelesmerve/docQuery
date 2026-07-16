# arksoft-pipeline

Exchange Server teknik belgelerini anonimleştirip zenginleştiren LangGraph pipeline'ı.

## Ne Yapar?

Ham Markdown belgelerini (sunucu adları, domain bilgileri, kişi isimleri içeren) alır ve:

1. **Görselleri OCR + VLM ile okur** — Qwen3-VL her ekran görüntüsünden metin çıkarır, Tesseract/EasyOCR ile doğrular
2. **Anonimleştirir** — Hostname, NetBIOS domain, veritabanı adı, e-posta, kişi isimlerini kurgusal değerlerle değiştirir
3. **Zenginleştirir** — Her görsele Türkçe açıklama üretir, gövdeyi Markdown formatına yapılandırır
4. **Metadata ekler** — YAML front-matter'a ürün, konfigürasyon tipi, anahtar kelimeler, özet yazar
5. **Kalite kontrol** — OCR güveni, eksik açıklama, PII sızıntısı denetler

## Pipeline Akışı

```
trigger
  → vision_validation_worker (paralel)
  → anonymize
  → code_extractor      ← kod bloklarını koruma altına alır
  → enrich              ← Qwen hiç kod görmez
  → code_injector       ← kodları geri yerleştirir
  → [metadata || qa]    (paralel)
  → finalize
```

## Kurulum

```bash
git clone <repo>
cd arksoft-pipeline
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Tesseract kurulumu (sistem paketi)
# Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-tur
# macOS:  brew install tesseract tesseract-lang

cp .env.example .env
# .env içinde VLLM_URL ve VLLM_MODEL'i düzenle
```

## Kullanım

```bash
# Belgelerinizi test_input/ altına koyun
# Görselleri test-images/ altına koyun

# Toplu çalıştır
python run_batch.py

# Kalite kontrol raporu
python check_outputs.py

# Tek belge
python graph.py
```

## Çıktılar

```
results/
  approved/      # QA sorunsuz geçen belgeler
  needs_review/  # Manuel inceleme gereken belgeler
```

## Anonimleştirme Sözlüğü

`anonymization_dict.json` — tüm belgeler boyunca tutarlılığı sağlar.
Sıfırlamak için: `rm -f anonymization_dict.json`

> **Not:** `test_input/`, `test-images/` ve `results/` klasörleri `.gitignore`'dadır.
> Müşteri verisi repoya girmez.

## Gereksinimler

- Python 3.11+
- vLLM sunucu (Qwen3-VL-30B, port 8001)
- Tesseract OCR (tur+eng dil paketi)
