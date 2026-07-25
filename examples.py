"""Read-only access to two explicitly selected, existing local results."""
from html import escape
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from flask import Blueprint, abort, jsonify, send_file
from markdown_it import MarkdownIt
import yaml

BASE = Path(__file__).resolve().parent
CATALOG = {
    'dag': ('DAG kurulumu', 'DAG_kurulumu_ve_Sunucuların_DAGa_eklenmesi'),
    'healthcheck': ('Exchange HealthCheck', 'Exchange_HealthCheckKomutlar_ve_Ekran_görüntüleri'),
}
examples = Blueprint('examples', __name__)


def document(key):
    if key not in CATALOG:
        abort(404)
    title, stem = CATALOG[key]
    candidates = [BASE / 'results' / 'approved' / ('ÖRNEK ÇIKTI --- ' + stem + '.md'),
                  BASE / 'results' / 'approved' / (stem + '.md'),
                  BASE / 'test_input' / (stem + '.md')]
    path = next((p for p in candidates if p.is_file() and not p.is_symlink()
                 and p.resolve().is_relative_to(BASE.resolve())), None)
    if path is None:
        abort(404, description='Yerel örnek dosyası bulunamadı.')
    return title, stem, path


def image_files(stem):
    return [p for p in sorted((BASE / 'test-images').glob(stem + '_img_*.png'))
            if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(BASE.resolve())]


@examples.get('/api/examples')
def listing():
    result = []
    for key, (title, _) in CATALOG.items():
        try:
            _, _, path = document(key)
            result.append(dict(id=key, title=title, available=True, path=path.relative_to(BASE).as_posix()))
        except Exception as exc:
            from werkzeug.exceptions import NotFound
            if not isinstance(exc, NotFound):
                raise
            result.append(dict(id=key, title=title, available=False))
    return jsonify(result)


@examples.get('/api/examples/<key>')
def detail(key):
    title, stem, path = document(key)
    content = path.read_text(encoding='utf-8-sig')
    metadata, body, warnings = {}, content, []
    front = re.match(r'\A---\n(.*?)\n---(?:\n|$)', content, re.S)
    if front:
        try:
            metadata = yaml.safe_load(front[1]) or {}
            if not isinstance(metadata, dict):
                raise ValueError()
            body = content[front.end():]
        except (yaml.YAMLError, ValueError):
            metadata = {}
            warnings.append('YAML metadata okunamadı; özgün Markdown korunuyor.')
    files = image_files(stem)
    by_name = {p.name: i for i, p in enumerate(files)}
    referenced = set()
    remote = set(re.findall(r'!\[.*?\]\((https?://.*?)\)', body, re.S))
    parser = MarkdownIt('commonmark', {'html': False}).enable('table')

    def render_image(renderer, tokens, idx, options, env):
        token = tokens[idx]
        src = token.attrGet('src') or ''
        parts = urlsplit(src)
        name = unquote(parts.path).replace('\\', '/').split('/')[-1]
        if not parts.scheme and not parts.netloc and name in by_name:
            referenced.add(name)
            return f'<img src="/api/examples/{key}/images/{by_name[name]}" alt="{escape(token.content or name, quote=True)}" loading="lazy">'
        remote.add(src)
        return '<em class="missing-image">[Görsel için doğrulanmış yerel eşleşme yok; dış kaynaktan yüklenmedi.]</em>'

    parser.add_render_rule('image', render_image)
    html = parser.render(body)
    if remote:
        warnings.append(f'{len(remote)} görsel referansı için yerel eşleşme yok. Uzak görseller indirilmedi.')
    return jsonify(id=key, title=title, path=path.relative_to(BASE).as_posix(),
                   content=content, html=html, metadata=metadata, warnings=warnings,
                   images=[dict(name=p.name, url=f'/api/examples/{key}/images/{i}',
                                referenced=p.name in referenced) for i, p in enumerate(files)])


@examples.get('/api/examples/<key>/download')
def download(key):
    _, _, path = document(key)
    return send_file(path, as_attachment=True, download_name=path.name)


@examples.get('/api/examples/<key>/images/<int:number>')
def image(key, number):
    _, stem, _ = document(key)
    files = image_files(stem)
    if number >= len(files):
        abort(404)
    return send_file(files[number], mimetype='image/png')
