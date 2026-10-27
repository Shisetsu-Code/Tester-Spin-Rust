"""Opt-in observation of already requested public JS; never sends requests."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def install(session_class):
    original = session_class.request

    def observed(self, method, url, *args, **kwargs):
        response = original(self, method, url, *args, **kwargs)
        try:
            source_url = str(response.url)
            if str(method).upper() == 'GET' and response.status_code == 200 and urlsplit(source_url).path.endswith('.js'):
                content = response.content
                if len(content) <= 8 * 1024 * 1024:
                    from tester_spin.run_diagnostics import sanitize
                    root = Path(os.environ['CI_PUBLIC_ASSETS']); root.mkdir(parents=True, exist_ok=True)
                    if len(list(root.glob('*.json'))) < 100:
                        sha = hashlib.sha256(content).hexdigest()
                        (root / (sha + '.json')).write_text(json.dumps({'url': sanitize(source_url),
                            'source_sha256': sha, 'sanitized': True,
                            'text': sanitize(content.decode('utf-8'))}), encoding='utf-8')
        except Exception:
            pass  # Observation must never affect the original request/result.
        return response

    session_class.request = observed


if os.environ.get('CI_PUBLIC_ASSETS'):
    for module in ('requests', 'curl_cffi.requests'):
        try:
            from importlib import import_module
            install(import_module(module).Session)
        except ImportError:
            pass
