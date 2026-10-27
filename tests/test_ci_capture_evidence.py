"""Synthetic transport envelopes: diagnostic export must not leak session data."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
spec = importlib.util.spec_from_file_location('ci_capture_evidence', ROOT / 'scripts/ci_capture_evidence.py')


class CaptureExportTests(unittest.TestCase):
    def load(self):
        self.assertTrue(spec.origin and Path(spec.origin).is_file(), 'Diagnostic exporter is missing')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_nested_wire_json_form_and_headers_are_redacted(self):
        module = self.load()
        sample = {'token': 'top-secret', 'headers': [{'name': 'Cookie', 'value': 'private'}],
                  'text': '{"sessionUuid":"nested-secret","round":{"status":"completed"}}',
                  'form': 'symbol=demo&mgckey=wire-secret&bl=0'}
        value = module.clean(sample)
        encoded = json.dumps(value)
        for secret in ('top-secret', 'nested-secret', 'wire-secret', 'private'):
            self.assertNotIn(secret, encoded)
        self.assertIn('completed', encoded)
        self.assertIn('symbol', encoded)

    def test_encoded_content_is_decoded_before_redaction(self):
        module = self.load()
        value = module.clean({'encoding': 'base64', 'text': 'eyJ0b2tlbiI6ImhpZGRlbiIsImJldCI6Mn0='})
        self.assertNotIn('eyJ0b2', json.dumps(value))
        self.assertNotIn('hidden', json.dumps(value))
        self.assertIn('bet', json.dumps(value))

    def test_export_omits_database_and_outside_symlinks(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'data'; root.mkdir()
            (root / 'result.json').write_text('{"token":"secret","state":"finished"}')
            (root / 'state.sqlite3').write_text('sensitive database')
            outside = Path(temp) / 'outside.json'; outside.write_text('{"unexpected":"outside"}')
            (root / 'link.json').symlink_to(outside)
            out = Path(temp) / 'export'
            module.export(root, out)
            files = list(out.rglob('*'))
            self.assertFalse(any(p.suffix == '.sqlite3' for p in files))
            contents = ''.join(p.read_text() for p in files if p.is_file())
            self.assertNotIn('sensitive database', contents)
            self.assertNotIn('unexpected', contents)
            self.assertNotIn('"secret"', contents)
            self.assertIn('finished', contents)
