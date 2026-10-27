"""Freeze a bounded public catalog sample without executing any game."""
from __future__ import annotations

import argparse
import contextlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))

from tester_spin.providers.registry import PROVIDERS, create_provider
from tester_spin.storage import Storage


def write_manifest(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.catalog-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def collect_catalog(provider, data_root, output, *, limit=3):
    if limit < 1:
        raise ValueError('The sample limit must be positive')
    output = Path(output)
    report = {
        'schema': 'tester-spin/ci-catalog-sample/v1',
        'provider': provider.key,
        'limit': limit,
        'selected': 0,
        'games': [],
        'catalog_complete': False,
        'note': 'Nonexhaustive catalog sample: first distinct records observed; max_pages=1. No gameplay executed.',
        'error': '',
    }
    write_manifest(output, report)
    stop = threading.Event()
    selected = set()
    storage = Storage(Path(data_root) / 'tester-spin.sqlite3')

    def select(game):
        if game.provider != provider.key:
            raise ValueError('Catalog provider identity mismatch')
        if game.slug in selected or len(selected) >= limit:
            return
        storage.upsert_games([game])
        selected.add(game.slug)
        report['games'].append({
            'provider': game.provider,
            'name': game.name,
            'slug': game.slug,
            'symbol': game.symbol,
            'url': game.url,
        })
        report['selected'] = len(selected)
        write_manifest(output, report)
        if len(selected) >= limit:
            stop.set()

    log_path = output.with_suffix('.private.log')
    with log_path.open('w', encoding='utf-8') as log:
        try:
            parameters = inspect.signature(provider.crawl_catalog).parameters
            options = {'max_pages': 1, 'stop_event': stop,
                       'progress': lambda message: print(message, file=log, flush=True)}
            if 'on_game' in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
                options['on_game'] = select
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                returned = provider.crawl_catalog(**options)
                for game in returned or []:
                    select(game)
                    if len(selected) >= limit:
                        break
        except InterruptedError:
            if not selected:
                report['error'] = 'CATALOG_CANCELLED_WITHOUT_SAMPLES'
        except Exception as exc:
            report['error'] = 'CATALOG_FAILURE: ' + type(exc).__name__
            traceback.print_exc(file=log)
    if not selected and not report['error']:
        report['error'] = 'CATALOG_EMPTY: no verifiable records selected'
    write_manifest(output, report)
    return report


def positive(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError('The sample limit must be positive')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', required=True, choices=PROVIDERS)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--limit', type=positive, default=3)
    args = parser.parse_args(argv)
    try:
        provider = create_provider(args.provider, args.data_root)
        report = collect_catalog(provider, args.data_root, args.output, limit=args.limit)
    except Exception as exc:
        report = {'schema': 'tester-spin/ci-catalog-sample/v1', 'provider': args.provider,
                  'limit': args.limit, 'selected': 0, 'games': [], 'catalog_complete': False,
                  'note': 'Nonexhaustive catalog sample. No gameplay executed.',
                  'error': 'CATALOG_FAILURE: ' + type(exc).__name__}
        write_manifest(args.output, report)
        with args.output.with_suffix('.private.log').open('a', encoding='utf-8') as log:
            traceback.print_exc(file=log)
    print(json.dumps({'provider': args.provider, 'selected': report['selected'],
                      'catalog_complete': False, 'error': report['error']}, ensure_ascii=False))
    return 0 if report['selected'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
