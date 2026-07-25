# DocQuery

## Arayüz ekran görüntüleri

Kullanıcının seçtiği iki ekran görüntüsü:

![DocQuery belge stüdyosu](docs/screenshots/document-studio.png)

![Önceki yerel alıntı görünümü ve kaynak görseli](docs/screenshots/previous-local-answer.png)

İkinci görüntü kaldırılan geçici yerel alıntı yönteminin önceki görünümüdür;
Qdrant veya Qwen modelinin ürettiği bir yanıtı göstermez. Güncel **Bilgiye sor**
ekranı `/api/ask` üzerinden gerçek Qdrant → embedding → yanıt modeli akışını
kullanır. Servisler çalışmıyorsa hata gösterilir; yerel yedek yanıt üretilmez.
Bu iki dosya kullanıcı tarafından README için özellikle seçilmiştir; orijinal
belge ve görsel klasörleri Git dışında tutulmaya devam eder.

## Web arayüzü — Belge stüdyosu

### Önceden üretilmiş iki yerel sonuç

Sayfanın üstündeki **Önceden üretilmiş sonuçlar** bölümünden **DAG kurulumu**
ve **Exchange HealthCheck** seçilebilir. Bu bölüm model gerektirmez; yeni OCR/AI
işi oluşturmaz, pipeline adımlarını tamamlanmış olarak işaretlemez, QA onayı
veya indekslenmiş olma iddiasında bulunmaz.

Okuma sırası: `results/approved/ÖRNEK ÇIKTI --- <belge>.md`, sonra
`results/approved/<belge>.md`, sonra `test_input/<belge>.md`.
Arayüz seçilen gerçek dosya yolunu gösterir. Mevcut yerel dosyalarda DAG sonucu
`results/approved/` içindeki kopyadan, HealthCheck `test_input/` içinden okunur.
`test_input` konumu bu iki sonuç için yeni işlem girdisi anlamına gelmez.

YAML front matter metadata olarak gösterilir; olmayan alanlar üretilmez.
**Sonuç Markdown** özgün metni gösterir; indirme dosyanın baytlarını değiştirmez.
`test-images/` içindeki belge adına ait görseller galeride açılır ve indirilebilir.
Doğrudan Markdown referansı eşleşen görseller belge içine de yerleştirilir.
Uzak OneNote görselleri indirilmez ve yerel dosyalara tahminen bağlanmaz.
Görsellere bu görünümde yeni anonimleştirme uygulanmaz.

Dosyalar yerlerinde kalır; ham belgeler ve kaynak görseller repoya eklenmez.
README için kullanıcının seçtiği yukarıdaki iki görüntü istisnadır.
Örnekler otomatik olarak RAG indeksine alınmaz.
Yerel doğrulama (sunucu açık, Edge kurulu):

```powershell
.venv\Scripts\python web_tests/examples_browser.py
```

Bu test sadece görüntüleme ve indirmeyi kontrol eder; iş başlatmaz.
İki belge, dokuz yerel görsel, görsel büyütme, Markdown görünümü ve özgün
dosyayla birebir indirme Edge ile kontrol edildi. Mobil yatay taşma veya
JavaScript hatası görülmedi; test sırasında POST isteği gönderilmedi.

8080 başka bir uygulama süreci tarafından kullanılıyorsa farklı port seçilebilir:

```powershell
$env:DOCQUERY_PORT="8081"
.venv\Scripts\python web.py
# Tarayıcı: http://127.0.0.1:8081
```

Python merkezli projeye **Flask + HTML/CSS/JavaScript** eklendi. Node veya frontend
derlemesi gerektirmez; mevcut LangGraph akışı ve `rag.RAG` kullanılır. Waitress
yerel HTTP sunucusudur. Mobil görünüm, klavye ile kullanım, gerçek işlem adımları,
kalite uyarıları, Markdown önizleme/indirme ve kaynak parçalı soru-cevap içerir.

### Kurulum ve çalıştırma

Python 3.11+ ile, proje kökünde:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-web.txt
# Yalnızca .env henüz yoksa:
Copy-Item .env.example .env
# .env içindeki servis adreslerini ve model adlarını düzenleyin.
.venv\Scripts\python web.py
```

Tarayıcı: **http://127.0.0.1:8080**. Linux/macOS'ta `.venv/bin/python` kullanın.
Servisler kapalıyken de arayüz açılır; uydurma belge veya yanıt göstermez.
`.env` değişikliklerinden sonra sunucuyu yeniden başlatın.

| Bileşen | Gereken ayar / kurulum |
| --- | --- |
| Belge işleme ve yanıt modeli | `VLLM_URL`, `VLLM_MODEL`; görseller için vision destekli OpenAI uyumlu chat endpoint. İsteğe bağlı `VLLM_API_KEY`. |
| Embedding | `EMBEDDING_URL`, `EMBEDDING_MODEL`; Türkçe destekli `/v1/embeddings` servisi. İsteğe bağlı `EMBEDDING_API_KEY`. |
| Qdrant | `docker compose up -d qdrant`; `QDRANT_URL`, gerekiyorsa `QDRANT_API_KEY`. |
| Görsel doğrulama | `pip install pytesseract` ve sistemde Tesseract `tur+eng` dil paketleri. Alternatif motor için `pip install easyocr`. Mevcut tam pipeline bağımlılıkları `requirements.txt` içinde. |

OCR kurulmamışsa görsel kontrolü başarılı sayılmaz; belge incelemeye yönlendirilir.
Servis durum göstergesi `/models` veya Qdrant `/collections` erişimini kontrol eder;
model yüklenmesini veya üretim kalitesini garanti etmez. `/models` sağlamayan uyumlu
servislerde gösterge erişilemez diyebilir; gerçek işlem çağrısı yine denenebilir.

### Kullanım

1. UTF-8 `.md` belge seçin. PDF/DOCX dönüşümü bu sürümde yoktur.
2. Belgedeki görselleri ayrıca ekleyin: PNG/JPG/WebP, en fazla 20 adet, toplam
   istek boyutu 25 MB. Referansın dosya adı yüklemeyle aynı olmalı
   (`images/ekran.png` → `ekran.png`).
3. **Belgeyi yükle**, ardından belge satırındaki **İşlemi başlat** düğmesine basın.
   Durumlar: hazır → sırada → işleniyor → onaylı / inceleme gerekli / başarısız.
   İlerleme tamamlanan LangGraph düğümleridir, tahmini yüzde değildir.
4. **İncele** ile kalite uyarılarını, biçimlendirilmiş belgeyi veya Markdown
   kaynağını görün; **Markdown indir** ile çıktıyı alın. Ham görseller PII
   içerebileceğinden önizlemede gösterilmez; görsel açıklamaları metinde kalır.
5. **Onaylıları indeksle** yalnızca QA onaylı web belgelerini Qdrant'a aktarır.
   Uyarılı belgeleri zorla onaylama yoktur; kaynağı düzeltip tekrar yükleyin.
6. **Bilgiye sor** ekranından sorun. Yanıtla birlikte belge, parça numarası,
   benzerlik ve kaynak metni gösterilir. Kaynak yoksa veya servis hata verirse
   bu durum açıkça belirtilir.

Web yüklemeleri, durumları, çıktıları ve belgeye özel anonimleştirme sözlükleri
`.web-data/` altında kalır; tamamı Git dışında tutulur. Yükleme akışı mevcut
şirket belgelerini kendiliğinden işlemez. Yukarıdaki iki seçili yerel sonuç
salt okunur örnek panelinde gösterilir.
Web Qdrant alias'ı `WEB_QDRANT_COLLECTION=docquery_web_documents` olup CLI
indeksinden ayrıdır. İndeks tamamlanmadan aktif alias değiştirilmez.
Anonimleştirme eşleştirmeleri web belgeleri arasında ortak değildir.

Bu sürüm tek kullanıcılı yerel uygulamadır; `127.0.0.1` üzerinde tek sunucu
çalıştırın. İşler sırayla, ayrı pipeline süreçlerinde yürütülür (30 dakika
sınırı). Durumlar diskte saklanır; yeniden başlatmada yarım işler yeniden
denenebilir hata durumuna alınır. Kullanıcı yönetimi ve dağıtık görev kuyruğu yoktur.
Yüklenen içerik işlem sırasında yapılandırılmış model servislerine gönderilir.
Ham HTML çalıştırılmaz, harici görseller yüklenmez, yükleme boyutu ve dosya
türleri doğrulanır; POST istekleri oturum token'ı gerektirir.

### Ekran görüntüleri

Çalışan uygulamanın **boş çalışma alanı**, gerçek servis durumlarıyla çekildi.
Şirket belgesi veya örnek sonuç içermez.

![DocQuery masaüstü belge stüdyosu](docs/screenshots/studio.png)

<img src="docs/screenshots/mobile.png" alt="DocQuery 390 piksel mobil görünüm" width="300">

### Doğrulama

```powershell
.venv\Scripts\python -m unittest discover -s web_tests -v
.venv\Scripts\python -m unittest discover -s tests -v
# Ayrı terminalde web.py çalışırken, Microsoft Edge kurulu Windows üzerinde:
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python web_tests/browser_smoke.py
```

Tarayıcı testi sentetik bir belge yükler ve gerçek servisleri çağırır; yalnızca
boş çalışma alanında ekran görüntüsü yazar. Test belgesi `.web-data/` içinde kalır.
Testler şirket verisi kullanmaz. API/pipeline testlerindeki sentetik model
yanıtları ve bellek içi Qdrant yalnızca testlerde kullanılır; uygulamada demo modu yoktur.

26 Eylül 2026 doğrulaması: 20 web/pipeline ve mevcut 8 RAG testi geçti; Edge ile
1440 px masaüstü ve 390 px mobil görünüm, gezinme, soru gönderme, yükleme ve
işlem başlatma kontrol edildi. JavaScript hatası veya mobil yatay taşma görülmedi.
Bu ortamda vLLM ve Qdrant erişilemiyordu, embedding modeli ayarlanmamıştı;
gerçek başarılı model üretimi ve uzak Qdrant indekslemesi doğrulanamadı.
Tarayıcıda servis hatası akışı doğrulandı. Başarı yolları test doubles ve bellek
içi Qdrant ile doğrulandı; bunlar gerçek servis entegrasyonu testi değildir.

Dosya yükleme ve güvenlik yaklaşımı için:
[Flask güvenlik belgeleri](https://flask.palletsprojects.com/en/stable/web-security/).

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
