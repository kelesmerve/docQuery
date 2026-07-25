"""Shared model transport with optional authentication and strict web errors."""
import os
import requests


def post(url, **kwargs):
    if os.getenv('VLLM_API_KEY'):
        kwargs.setdefault('headers', {})['Authorization'] = 'Bearer ' + os.environ['VLLM_API_KEY']
    response = requests.post(url, **kwargs)
    if os.getenv('DOCQUERY_STRICT') == '1':
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError('Model boş yanıt döndürdü.')
    return response
