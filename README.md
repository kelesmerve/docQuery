# DocQuery

## Qdrant ile RAG / Soru-cevap

`rag.py`, yalnızca `results/approved/**/*.md` belgelerini parçalara ayırıp
embedding vektörleriyle Qdrant'a yükler. İlgili parçalar mevcut vLLM modeline
gönderilir; Türkçe yanıt ve kaynak dosya/parça bilgileri döner.
`needs_review` ve ham belgeler indekslenmez. Kullanım komut satırındandır.

```powershell
pip install -r requirements-rag.txt
docker compose up -d qdrant
# .env yoksa .env.example dosyasını .env olarak kopyalayın.
# EMBEDDING_URL ve EMBEDDING_MODEL değerlerini çalışan servisinize göre doldurun.
# Yanıt üretimi için VLLM_URL ve VLLM_MODEL değerlerini ayarlayın.
python rag.py index
python rag.py ask "Exchange DAG nasıl yapılandırılır?"
python rag.py ask "Sertifika yenileme adımları nelerdir?" --top-k 5 --json
```

Embedding servisi `/v1/embeddings` biçiminde `model` ve `input` kabul etmeli,
`data` içinde `index` ve `embedding` döndürmelidir. Türkçe destekleyen bir
embedding modeli kullanın; sohbet modelinin embedding ürettiğini varsaymayın.
Modeli değiştirdiğinizde yeniden indeksleyin. `.env` otomatik yüklenir.
RAG bağımlılıkları ayrıdır; belge üretmek için ana `requirements.txt` de gereklidir.

Her `index` çalışması yeni bir tam koleksiyon oluşturur; tüm yükleme başarılı
olduğunda aktif alias yeni koleksiyona geçirilir. Güncellenen/silinen belgeler
bir sonraki başarılı indekslemede yansır. Boş dizin indekslenmez ve önceki
indeks korunur. İndekslemeleri aynı anda çalıştırmayın. Eski ve başarısız
yükleme koleksiyonları otomatik silinmez; disk kullanımı için Qdrant üzerinden
kullanılmayanları temizleyin. `QDRANT_COLLECTION` yeni bir alias adı olmalıdır;
mevcut fiziksel koleksiyonun adını kullanmayın.

Parça boyutu/örtüşmesi karakter cinsindendir. `RAG_SCORE_THRESHOLD` kosinüs
benzerlik eşiğidir; modelinize göre ayarlayın. Kaynak bulunamazsa yanıt modeli
çağrılmaz. Kaynak gösterme ve bilgi yetersizliğini belirtme talimatları modele
verilir; yanıt doğruluğu ayrıca değerlendirilmelidir. Onay durumu değiştiğinde
indekslemeyi tekrar çalıştırın.

Testler (harici model veya Docker gerektirmez):

```powershell
python -m unittest discover -s tests -v
```

Referans: [Qdrant Python istemcisi](https://github.com/qdrant/qdrant-client),
[alias API'si](https://api.qdrant.tech/api-reference/aliases/update-aliases).

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
git clone <repo> docquery
cd docquery
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
