"""Local, single-process DocQuery workspace. Run: python web.py."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_file, session
from markdown_it import MarkdownIt
from PIL import Image
import requests
import config
from web_worker import save

BASE = Path(__file__).resolve().parent
ROOT = BASE / '.web-data'
ROOT.mkdir(exist_ok=True)
app = Flask(__name__)
from examples import examples
app.register_blueprint(examples)
app.secret_key = secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=25 * 1024 * 1024, SESSION_COOKIE_SAMESITE='Strict',
                  SESSION_COOKIE_HTTPONLY=True, TRUSTED_HOSTS=['localhost', '127.0.0.1'])
pool = ThreadPoolExecutor(max_workers=1)
index_lock = threading.Lock()
index_state = {'status': 'idle'}
md = MarkdownIt('commonmark', {'html': False})
# Raw screenshots can contain PII. Never embed uploaded or remote images in output.
md.add_render_rule('image', lambda *args: '<em>[Görsel: kaynak dosyada]</em>')


def job_path(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        abort(404)
    path = ROOT / job_id
    if not (path / 'status.json').exists():
        abort(404)
    return path


def read_status(path):
    return json.loads((path / 'status.json').read_text(encoding='utf-8'))


@app.before_request
def protect():
    if request.method == 'POST' and not secrets.compare_digest(
        request.headers.get('X-CSRF-Token', ''), session.get('csrf', secrets.token_hex(32))
    ):
        abort(403, description='Oturum yenilendi. Sayfayı yenileyip tekrar deneyin.')


@app.after_request
def headers(response):
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(409)
@app.errorhandler(413)
def error(exc):
    return jsonify(error='Yükleme sınırı 25 MB.' if exc.code == 413 else exc.description), exc.code


@app.get('/')
def home():
    session.setdefault('csrf', secrets.token_hex(32))
    return render_template('index.html', csrf=session['csrf'])


@app.get('/api/services')
def services():
    def probe(url, key='', qdrant=False):
        try:
            r = requests.get(url, timeout=2, headers={('api-key' if qdrant else 'Authorization'): (key if qdrant else 'Bearer ' + key)} if key else {})
            return 'online' if r.ok else 'unavailable'
        except requests.RequestException:
            return 'unavailable'
    model_base = config.VLLM_URL.rsplit('/chat/completions', 1)[0]
    embedding = os.getenv('EMBEDDING_URL', '')
    with ThreadPoolExecutor(max_workers=3) as probes:
        v = probes.submit(probe, model_base + '/models', os.getenv('VLLM_API_KEY', ''))
        q = probes.submit(probe, os.getenv('QDRANT_URL', 'http://localhost:6333') + '/collections', os.getenv('QDRANT_API_KEY', ''), True)
        e = probes.submit(probe, embedding.rsplit('/embeddings', 1)[0] + '/models', os.getenv('EMBEDDING_API_KEY', '')) if embedding and os.getenv('EMBEDDING_MODEL') else None
        return jsonify(model=v.result(), qdrant=q.result(), embedding=e.result() if e else 'unconfigured')


@app.get('/api/jobs')
def jobs():
    return jsonify(sorted([read_status(p.parent) for p in ROOT.glob('*/status.json')],
                          key=lambda j: j['created'], reverse=True))


@app.post('/api/jobs')
def upload():
    document = request.files.get('document')
    images = [item for item in request.files.getlist('images') if item.filename]
    if not document or not document.filename.lower().endswith('.md'):
        abort(400, description='Bir UTF-8 Markdown (.md) belgesi seçin.')
    try:
        content = document.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        abort(400, description='Belge UTF-8 kodlamasında olmalı.')
    if not content.strip() or len(content) > 500_000:
        abort(400, description='Belge boş olamaz; metin sınırı 500.000 karakter.')
    if len(images) > 20:
        abort(400, description='En fazla 20 görsel yükleyebilirsiniz.')
    validated = {}
    for item in images:
        name = item.filename or ''
        if not re.fullmatch(r'[\w .-]+\.(?:png|jpg|jpeg|webp)', name, re.I) or name in validated:
            abort(400, description='Görsel adları benzersiz olmalı; PNG, JPG veya WebP kullanın.')
        blob = item.read()
        try:
            with Image.open(BytesIO(blob)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 25_000_000:
                    raise ValueError()
                image.verify()
        except Exception:
            abort(400, description='Geçersiz veya çok büyük görsel (en fazla 25 megapiksel).')
        validated[name] = blob
    job_id = uuid4().hex
    path = ROOT / job_id
    (path / 'images').mkdir(parents=True)
    (path / 'input.md').write_text(content, encoding='utf-8')
    for name, blob in validated.items():
        (path / 'images' / name).write_bytes(blob)
    data = dict(id=job_id, name=document.filename.replace('\\', '/').split('/')[-1],
                created=datetime.now(timezone.utc).isoformat(), status='ready', steps=[], issues=[])
    save(path / 'status.json', data)
    return jsonify(data), 201


def process(path):
    try:
        result = subprocess.run([sys.executable, str(BASE / 'web_worker.py'), str(path)],
                                cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=1800, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        data = read_status(path)
        if result.returncode or data['status'] in ('running', 'queued'):
            raise RuntimeError()
    except Exception:
        data = read_status(path)
        data.update(status='error', error='İşlem durdu veya 30 dakika sınırını aştı. Servisleri kontrol edip yeniden deneyin.')
        save(path / 'status.json', data)


start_lock = threading.Lock()


@app.post('/api/jobs/<job_id>/start')
def start(job_id):
    path = job_path(job_id)
    with start_lock:
        data = read_status(path)
        if data['status'] not in ('ready', 'error'):
            abort(409, description='Bu belge zaten işleniyor veya tamamlandı.')
        data.update(status='queued', steps=[], error=None)
        save(path / 'status.json', data)
        pool.submit(process, path)
    return jsonify(data), 202


@app.get('/api/jobs/<job_id>')
def detail(job_id):
    path = job_path(job_id)
    data = read_status(path)
    if data['status'] in ('approved', 'review'):
        content = (path / 'output.md').read_text(encoding='utf-8')
        data.update(content=content, html=md.render(content))
    return jsonify(data)


@app.get('/api/jobs/<job_id>/download')
def download(job_id):
    path = job_path(job_id)
    if read_status(path)['status'] not in ('approved', 'review'):
        abort(409, description='İndirilebilir çıktı henüz yok.')
    return send_file(path / 'output.md', as_attachment=True, download_name='docquery-' + job_id[:8] + '.md')


def build_index():
    global index_state
    service = None
    try:
        import rag
        # Only this application's QA-approved documents; never read company fixtures.
        approved = ROOT / 'approved'
        approved.mkdir(exist_ok=True)
        for p in ROOT.glob('*/status.json'):
            data = read_status(p.parent)
            if data['status'] == 'approved':
                (approved / (data['id'] + '.md')).write_text(
                    (p.parent / 'output.md').read_text(encoding='utf-8'), encoding='utf-8')
        rag.OUTPUT_APPROVED_DIR = str(approved)
        service = rag.RAG()
        service.alias = os.getenv('WEB_QDRANT_COLLECTION', 'docquery_web_documents')
        index_state = dict(status='done', **service.index())
    except Exception as exc:
        index_state = dict(status='error', error='İndeksleme tamamlanamadı. Qdrant ve embedding ayarlarını kontrol edin. (' + type(exc).__name__ + ')')
    finally:
        if service:
            service.client.close()
        index_lock.release()


@app.route('/api/index', methods=['GET', 'POST'])
def index():
    global index_state
    if request.method == 'POST':
        if not any(read_status(p.parent)['status'] == 'approved' for p in ROOT.glob('*/status.json')):
            abort(409, description='Önce kalite kontrolünden geçmiş bir belge gerekli.')
        if not index_lock.acquire(blocking=False):
            abort(409, description='İndeksleme zaten çalışıyor.')
        index_state = {'status': 'running'}
        pool.submit(build_index)
    return jsonify(index_state)


@app.post('/api/ask')
def ask():
    body = request.get_json(silent=True) or {}
    question = body.get('question')
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
        abort(400, description='Soru 1–4000 karakter olmalı.')
    service = None
    try:
        import rag
        service = rag.RAG()
        service.alias = os.getenv('WEB_QDRANT_COLLECTION', 'docquery_web_documents')
        return jsonify(service.ask(question))
    except Exception as exc:
        return jsonify(error='Yanıt üretilemedi. Onaylı belgeleri indeksleyin; Qdrant, embedding ve yanıt modelinin çalıştığını kontrol edin. (' + type(exc).__name__ + ')'), 503
    finally:
        if service:
            service.client.close()


if __name__ == '__main__':
    for p in ROOT.glob('*/status.json'):
        data = read_status(p.parent)
        if data['status'] in ('queued', 'running'):
            data.update(status='error', error='Sunucu yeniden başlatıldı. İşlemi yeniden başlatın.')
            save(p, data)
    from waitress import serve
    port = int(os.getenv('DOCQUERY_PORT', '8080'))
    print(f'DocQuery: http://127.0.0.1:{port}', flush=True)
    serve(app, host='127.0.0.1', port=port, threads=8)
