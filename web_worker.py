"""Isolated pipeline process; progress is written atomically for the web server."""
import json
import os
from pathlib import Path
import sys


def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def main():
    root = Path(sys.argv[1]).resolve()
    status = root / 'status.json'
    data = json.loads(status.read_text(encoding='utf-8'))
    try:
        import config
        config.IMAGE_DIR = str(root / 'images')
        import pipeline.anonymizer as anonymizer
        anonymizer.DICT_PATH = str(root / 'dictionary.json')
        import graph
        state = dict(markdown_path=str(root / 'input.md'), markdown_content='',
                     original_markdown='', image_refs=[], vision_outputs={},
                     validation_results={}, anonymization_map={}, qa_issues=[],
                     enriched_content='', metadata_yaml={}, extracted_codes={})
        data.update(status='running', steps=[])
        save(status, data)
        for event in graph.app.stream(state, stream_mode='updates'):
            for node, update in event.items():
                if update:
                    for key, value in update.items():
                        if key == 'qa_issues':
                            state[key].extend(value)
                        elif key in ('vision_outputs', 'validation_results'):
                            state[key].update(value)
                        else:
                            state[key] = value
                if node not in data['steps']:
                    data['steps'].append(node)
                save(status, data)
        from pipeline.qa import collect_qa_issues
        issues = list(dict.fromkeys(state['qa_issues'] + collect_qa_issues(state)))
        content = state['enriched_content']
        if not content.strip():
            raise ValueError('Model boş belge döndürdü.')
        (root / 'output.md').write_text(content, encoding='utf-8')
        data.update(status='review' if issues else 'approved', issues=issues)
    except Exception as exc:
        # Do not expose service URLs, credentials or document content in errors.
        data.update(status='error', error=('İşlem tamamlanamadı (' + type(exc).__name__ +
                    '). Model bağlantısını, bağımlılıkları ve OCR kurulumunu kontrol edin.'))
    save(status, data)


if __name__ == '__main__':
    os.environ['DOCQUERY_STRICT'] = '1'
    main()
