#!/usr/bin/env python3
"""Passive CI evidence summaries; never instantiate providers or execute games."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from tester_spin.providers.registry import PROVIDERS
from tester_spin.run_diagnostics import sanitize
from tester_spin.storage import Storage

MAX_JSON = 2 * 1024 * 1024
EVIDENCE_NAMES = ('result.json', 'diagnostic.json', 'path-coverage.json', 'sample-catalog.json', 'run-tree.json', 'paid-option-inventory.json')


class ReadOnlyStorage(Storage):
    """Reuse canonical selection/result readers without initialization or workers."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        self._lock = threading.RLock()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        try:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA query_only=ON')
            yield con
        finally:
            con.close()


def read_json(path, max_bytes=MAX_JSON):
    if path.stat().st_size > max_bytes:
        raise ValueError(f'JSON exceeds {max_bytes} byte size limit')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def copy_evidence(result, data_root, output, index):
    """Only bounded sanitized JSON indexes, confined to this audit's data root."""
    evidence, errors, documents = [], [], {}
    run_dir = result.get('run_dir')
    if not run_dir:
        return evidence, errors, documents
    root = Path(data_root).resolve()
    directory = Path(run_dir).resolve()
    try:
        directory.relative_to(root)
    except ValueError:
        return [], ['Run evidence directory is outside data root; skipped'], {}
    for name in EVIDENCE_NAMES:
        source = directory / name
        if not source.is_file():
            continue
        try:
            source.resolve().relative_to(root)
            payload = sanitize(read_json(source))
            documents[name] = payload
            destination = Path(output) / 'evidence' / str(index) / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            evidence.append(destination.relative_to(output).as_posix())
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f'{name}: {exc}')
    return evidence, errors, documents


def summarize_attempts(attempts):
    groups = {}
    for attempt in attempts:
        key = (str(attempt.get('mode_id', 'UNKNOWN')), str(attempt.get('mode_kind', 'UNKNOWN')))
        mode = groups.setdefault(key, dict(mode_id=key[0], mode_kind=key[1], attempts=0, ok=0, terminal=0, ok_terminal=0))
        mode['attempts'] += 1
        mode['ok'] += attempt.get('ok') is True
        mode['terminal'] += attempt.get('terminal') is True
        mode['ok_terminal'] += (attempt.get('ok') is True and attempt.get('terminal') is True
                                and not attempt.get('error') and not attempt.get('warning'))
    return list(groups.values())


def totals(games):
    return dict(catalog_games=len(games), selected=sum(g['selected'] for g in games),
                attempted=sum(g['attempted'] for g in games), result_recorded=sum(g['result_recorded'] for g in games),
                closed_base_rounds=sum(g['closed_base_rounds'] for g in games),
                statuses=dict(Counter(g['status'] for g in games)))


def build_provider_report(provider, data_root, output, *, limit=3, catalog_exit=0, run_exit=0, spins=2):
    data_root, output = Path(data_root), Path(output)
    # Catalog-only identity is registry metadata; importing implementations would
    # unnecessarily load browser/network dependencies in this passive reporter.
    supported = PROVIDERS[provider][0] != 'catalogs.adapter'
    games, results, errors = [], [], []
    try:
        store = ReadOnlyStorage(data_root / 'tester-spin.sqlite3')
        games = store.list_games(provider)  # Same name COLLATE NOCASE order as CLI.
        results = store.latest_results(provider)  # Canonical final callback status.
    except (OSError, sqlite3.Error, ValueError) as exc:
        errors.append(f'Catalog/result storage unavailable: {exc}')
    selected = {g.slug for g in (games[:limit] if limit else games)}
    by_slug = {r.get('slug'): r for r in results}
    rows = []
    for index, game in enumerate(games):
        chosen = game.slug in selected
        result = by_slug.get(game.slug) if chosen and supported else None
        attempts = result.get('attempts', []) if result else []
        modes = summarize_attempts(attempts)
        closed = sum(m['ok_terminal'] for m in modes if m['mode_kind'] == 'SPIN' and m['mode_id'] == 'SPIN')
        status = (result.get('status') or 'RESULTADO_SIN_ESTADO') if result else ('SIN_EJECUTOR' if chosen and not supported else 'NO_EJECUTADO')
        row = dict(provider=provider, slug=game.slug, name=game.name, url=game.url,
                   selected=chosen, attempted=bool(attempts), result_recorded=result is not None,
                   status=status, error=result.get('error', '') if result else '',
                   requested_spins=result.get('requested_spins') if result else None,
                   successful_spins=result.get('successful_spins', 0) if result else 0,
                   failed_spins=result.get('failed_spins', 0) if result else 0,
                   closed_base_rounds=closed, attempts=modes,
                   feature_domains=result.get('feature_domains', {}) if result else {},
                   coverage_issues=[], evidence=[])
        if result:
            evidence, issues, docs = copy_evidence(result, data_root, output, index)
            coverage = docs.get('path-coverage.json', {})
            diagnostic = docs.get('diagnostic.json', {})
            row.update(evidence=evidence, coverage=coverage,
                       coverage_issues=issues + diagnostic.get('evidence_gaps', []) +
                       [b for b in coverage.get('branch_points', []) if b.get('missing') or b.get('complete') is False],
                       result=sanitize(result))
            artifact_status = docs.get('result.json', {}).get('status')
            if artifact_status and artifact_status != status:
                row['coverage_issues'].append({'code': 'ARTIFACT_STATUS_DIFFERS', 'artifact_status': artifact_status,
                                               'canonical_status': status, 'authority': 'Storage.latest_results'})
        rows.append(row)
    if not games:
        errors.append('No catalog games were persisted; no games selected or claimed executed.')
    for label, code in [('catalog', catalog_exit), ('run', run_exit)]:
        if code:
            errors.append(f'{label} command exited {code}; inspect sanitized log excerpts and workflow logs')
    logs = {}
    for name in ('catalog.log', 'execution.log', 'run.log'):
        for directory in (output, data_root):
            path = directory / name
            if path.is_file():
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 16384))
                    logs[name] = stream.read(16384).decode('utf-8', errors='replace')
                break
    report = dict(schema='tester-spin/ci-audit/v1', provider=provider, display_name=PROVIDERS[provider][2],
                  generated_at=datetime.now(timezone.utc).isoformat(), execution_supported=supported,
                  state='CATALOGO_FALLIDO' if not games else ('SIN_EJECUTOR' if not supported else 'RESULTADOS'),
                  catalog_exit=catalog_exit, run_exit=run_exit, requested_spins=spins, limit=limit,
                  spins_meaning='Requested samples per path; actual closed base rounds are reported separately.',
                  selection_order='Storage.list_games: name COLLATE NOCASE ASC; first limit',
                  result_authority='Storage.latest_results; artifact JSON cannot upgrade final callback status',
                  attempted_meaning='Games with recorded SpinAttempt evidence, not catalog discovery or a result alone.',
                  errors=errors, log_excerpts=logs, games=rows, **totals(rows))
    return sanitize(report)


def cell(value):
    return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def write_reports(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = sanitize(report)
    (output / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    columns = ['provider', 'slug', 'name', 'selected', 'attempted', 'result_recorded', 'status',
               'requested_spins', 'successful_spins', 'failed_spins', 'closed_base_rounds', 'error',
               'attempts', 'feature_domains', 'coverage_issues', 'evidence']
    with (output / 'audit.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for game in report['games']:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in game.items()})
    lines = ['# Auditoría real de CI', '',
             f"Catálogo: {report['catalog_games']} · Seleccionados: {report['selected']} · Con intentos registrados: {report['attempted']} · Resultados: {report['result_recorded']} · Cierres base: {report['closed_base_rounds']}", '',
             'Estados finales automáticos conservados desde SQLite. El catálogo no prueba ejecución. Los cierres base no certifican cobertura completa. Dos spins solicitan muestras por ruta.', '']
    providers = report.get('providers', [report])
    lines += ['| Proveedor | Estado | Catálogo | Seleccionados | Con intentos | Resultados | Cierres base | Estados finales |', '|---|---|---:|---:|---:|---:|---:|---|']
    for provider in providers:
        lines.append('| ' + ' | '.join(cell(provider.get(k, '')) for k in ('provider', 'state', 'catalog_games', 'selected', 'attempted', 'result_recorded', 'closed_base_rounds', 'statuses')) + ' |')
        for error in provider.get('errors', []):
            lines += ['', f"{cell(provider['provider'])}: {cell(error)}", '']
    lines += ['', '## Lista completa', '', '| Proveedor | Juego | Seleccionado | Con intentos | Final | Correctos/fallidos | Cierres base | Error / cobertura | Evidencia |', '|---|---|---|---|---|---|---:|---|---|']
    for g in report['games']:
        values = (g['provider'], g['name'], g['selected'], g['attempted'], g['status'],
                  f"{g['successful_spins']}/{g['failed_spins']}", g['closed_base_rounds'],
                  g['error'] or json.dumps(g['coverage_issues'], ensure_ascii=False), ', '.join(g['evidence']))
        lines.append('| ' + ' | '.join(map(cell, values)) + ' |')
    (output / 'audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def aggregate_reports(source, output):
    output = Path(output).resolve()
    reports = []
    for path in sorted(Path(source).rglob('audit.json')):
        if path.parent.resolve() == output:
            continue
        report = read_json(path, 16 * MAX_JSON)
        if report.get('schema') != 'tester-spin/ci-audit/v1' or not report.get('provider'):
            continue
        for row in report['games']:
            copied = []
            for name in row['evidence']:
                try:
                    source_path = (path.parent / name).resolve()
                    relative = source_path.relative_to(path.parent.resolve())
                    if source_path.name not in EVIDENCE_NAMES or report['provider'] not in PROVIDERS:
                        raise ValueError('Evidence is not an allowed provider JSON index')
                    payload = sanitize(read_json(source_path))
                    suffix = Path(*relative.parts[1:]) if relative.parts[0] == 'evidence' else relative
                    target = output / 'evidence' / report['provider'] / suffix
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
                    copied.append(target.relative_to(output).as_posix())
                except (OSError, ValueError, UnicodeError) as exc:
                    row['coverage_issues'].append({'code': 'AGGREGATE_EVIDENCE_UNAVAILABLE', 'detail': str(exc)})
            row['evidence'] = copied
        reports.append(report)
    if not reports:
        raise ValueError('No provider audit.json reports found')
    games = [game for report in reports for game in report['games']]
    combined = dict(schema='tester-spin/ci-audit-combined/v1', providers=reports, games=games, **totals(games))
    write_reports(combined, output)
    return combined


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    provider = commands.add_parser('provider')
    provider.add_argument('--provider', choices=PROVIDERS, required=True)
    provider.add_argument('--data-root', type=Path, required=True)
    provider.add_argument('--output', type=Path, required=True)
    provider.add_argument('--limit', type=int, default=3)
    provider.add_argument('--spins', type=int, default=2)
    provider.add_argument('--catalog-exit', type=int, default=0)
    provider.add_argument('--run-exit', type=int, default=0)
    aggregate = commands.add_parser('aggregate')
    aggregate.add_argument('--input', type=Path, required=True)
    aggregate.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'provider':
            if args.limit < 0 or args.spins < 1:
                parser.error('--limit must be nonnegative and --spins must be positive')
            report = build_provider_report(args.provider, args.data_root, args.output, limit=args.limit,
                                           spins=args.spins, catalog_exit=args.catalog_exit, run_exit=args.run_exit)
            write_reports(report, args.output)
        else:
            report = aggregate_reports(args.input, args.output)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'Audit report failed: {sanitize(str(exc))}', file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in report.items() if k in {'provider', 'state', 'catalog_games', 'selected', 'attempted', 'result_recorded', 'closed_base_rounds', 'statuses', 'errors'}}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
