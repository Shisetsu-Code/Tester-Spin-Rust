#!/usr/bin/env python3
"""Bounded, passive export of sanitized protocol evidence for CI diagnosis."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from tester_spin.run_diagnostics import sanitize

SECRET = re.compile(r'(?i)(token|password|secret|cookie|authorization|session|state_lock|mgckey|^sid$|^sc$|^key$|api[_-]?key)')
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 180 * 1024 * 1024


def clean(value):
    if isinstance(value, dict):
        value = dict(value)
        if value.get('encoding') == 'base64' and isinstance(value.get('text'), str):
            try:
                value['text'] = base64.b64decode(value['text'], validate=True).decode('utf-8')
            except (ValueError, UnicodeError):
                value['text'] = '[BINARY OMITTED]'
            value['encoding'] = 'decoded-for-redaction'
        if 'base64' in value:
            value['base64'] = '[BINARY OMITTED]'
        return sanitize({k: clean(v) for k, v in value.items()})
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(('{', '[')):
            try:
                return json.dumps(clean(json.loads(stripped)), ensure_ascii=False)
            except (ValueError, RecursionError):
                pass
        if stripped.startswith('<'):
            try:
                tree = ET.fromstring(stripped)
                for node in tree.iter():
                    for key in list(node.attrib):
                        if SECRET.search(key):
                            node.attrib[key] = '[REDACTED]'
                    if SECRET.search(node.tag):
                        node.text = '[REDACTED]'
                value = ET.tostring(tree, encoding='unicode')
            except ET.ParseError:
                pass
        return sanitize(value)
    return value


def export(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    index, total = [], 0
    allowed = {'.json', '.jsonl', '.xml', '.txt', '.raw', '.har', '.js', '.html'}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in allowed:
            continue
        try:
            relative = path.resolve().relative_to(root)
            path.resolve().relative_to(output)
        except ValueError:
            pass
        else:
            continue
        try:
            relative = path.resolve().relative_to(root)
            size = path.stat().st_size
            if size > MAX_FILE or total + size > MAX_TOTAL:
                index.append({'path': str(relative), 'skipped': 'size_bound'})
                continue
            raw = path.read_bytes()
            text = raw.decode('utf-8-sig')
            try:
                content = json.loads(text)
            except ValueError:
                if path.suffix == '.jsonl':
                    content = [json.loads(line) for line in text.splitlines() if line.strip()]
                else:
                    content = {'text': text}
            target = output / (str(relative) + '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(clean(content), ensure_ascii=False), encoding='utf-8')
            total += size
            index.append({'path': str(relative), 'export': str(target.relative_to(output)),
                          'source_bytes': size, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                          'sanitized': True})
        except (ValueError, OSError, UnicodeError) as exc:
            index.append({'path': str(path.relative_to(root)), 'skipped': type(exc).__name__})
    (output / 'index.json').write_text(json.dumps(index, indent=2), encoding='utf-8')
    return index


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    items = export(args.root, args.output)
    print(json.dumps({'files_exported': sum('export' in x for x in items), 'files_skipped': sum('skipped' in x for x in items)}))
