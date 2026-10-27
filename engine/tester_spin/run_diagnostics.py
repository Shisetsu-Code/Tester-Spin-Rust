"""Passive, provider-neutral reports. This module never sends gameplay requests."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from tester_spin.models import GameTestResult

_SECRET = re.compile(r"(?i)(?:token|password|secret|cookie|authorization|session|state_lock|mgckey|^sid$|^sc$|^key$|api[_-]?key)")
_TEXT_SECRET = re.compile(r'(?i)((?:[\w-]*(?:token|password|secret|cookie|authorization|session)[\w-]*|state_lock|mgckey|sid|sc|key|api[_-]?key)\s*[=:]\s*)([^\s&,;\"\']+)')
_QUOTED_SECRET = re.compile(r'''(?i)(["'](?:[\w-]*(?:token|password|secret|cookie|authorization|session)[\w-]*|state_lock|mgckey|sid|sc|key|api[_-]?key)["']\s*:\s*)["'][^"']*["']''')
_AUTH_HEADER = re.compile(r'(?i)(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s;,]+')
_COOKIE_HEADER = re.compile(r'(?i)((?:set-cookie|cookie)\s*:\s*)[^\r\n]+')
_MAX_PARSE = 2 * 1024 * 1024


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        # HAR-style header/query arrays represent keys as name/value records.
        named_secret = isinstance(value.get('name'), str) and _SECRET.search(value['name'])
        return {str(k): '[REDACTED]' if _SECRET.search(str(k)) or (named_secret and str(k).casefold() == 'value')
                else sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = _COOKIE_HEADER.sub(r'\1[REDACTED]', value)
        value = _AUTH_HEADER.sub(r'\1[REDACTED]', value)
        value = _QUOTED_SECRET.sub(r'\1"[REDACTED]"', value)
        return _TEXT_SECRET.sub(r'\1[REDACTED]', value)
    return value


def _read_capture(path: Path) -> Any:
    if path.stat().st_size > _MAX_PARSE:
        raise ValueError('Capture exceeds comparison size limit; original preserved')
    text = path.read_text(encoding='utf-8-sig').strip()
    try:
        return sanitize(json.loads(text))
    except json.JSONDecodeError:
        if '=' in text and '\n' not in text and not text.startswith(('{', '[')):
            values: dict[str, list[str]] = {}
            for key, value in parse_qsl(text, keep_blank_values=True):
                values.setdefault(key, []).append(value)
            return sanitize({k: v[0] if len(v) == 1 else v for k, v in values.items()})
        raise ValueError('Not JSON or a single form-encoded message; inspect original')


def _flatten(value: Any, path: str = '$') -> dict[str, Any]:
    if isinstance(value, dict) and value:
        out = {}
        for key, child in value.items():
            suffix = '.' + key if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key) else '[' + json.dumps(key) + ']'
            out.update(_flatten(child, path + suffix))
        return out
    # Lists remain lists: order, duplicates, and empty containers are significant.
    return {path: value}


def compare_captures(before: Path, after: Path) -> dict[str, Any]:
    """Compare explicit captures without interpreting any provider's fields."""
    left, right = _flatten(_read_capture(before)), _flatten(_read_capture(after))
    differences = []
    equal = []
    for key in sorted(left.keys() | right.keys()):
        if key in left and key in right and json.dumps(left[key], sort_keys=True) == json.dumps(right[key], sort_keys=True):
            equal.append(key)
        else:
            differences.append({'path': key, 'before_present': key in left, 'after_present': key in right,
                                'before': left.get(key), 'after': right.get(key)})
    return {'differences': differences, 'equal_fields': equal,
            'interpretation': 'Differences are observations, not proof of causation. Secrets are redacted.'}


def _load(path: Path, gaps: list, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('expected object')
        return value
    except (OSError, ValueError) as exc:
        gaps.append({'code': 'INDEX_UNAVAILABLE', 'file': label, 'detail': str(exc)})
        return {}


def _order(path: Path) -> list:
    return [int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', path.as_posix())]


def _evidence(root: Path, directory: Path, gaps: list) -> list[dict]:
    try:
        directory = directory.resolve()
        directory.relative_to(root)
        if not directory.is_dir():
            raise ValueError('Capture directory missing')
    except (OSError, ValueError) as exc:
        gaps.append({'code': 'CAPTURE_DIRECTORY_UNAVAILABLE', 'detail': str(exc)})
        return []
    items = []
    for path in sorted(directory.rglob('*'), key=_order):
        if not path.is_file() or path.suffix.lower() not in {'.json', '.txt', '.raw', '.jsonl'}:
            continue
        if not any(tag in path.name.lower() for tag in ('request', 'response', 'wire', 'ws-attempt', 'http-', 'init', 'bootstrap')):
            continue
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(root).as_posix()
            digest = hashlib.sha256()
            with resolved.open('rb') as capture:
                for block in iter(lambda: capture.read(65536), b''):
                    digest.update(block)
            name = path.name.lower()
            kind = 'request' if 'request' in name else 'response' if 'response' in name else 'envelope'
            items.append({'path': relative, 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size, 'kind': kind})
        except (OSError, ValueError) as exc:
            gaps.append({'code': 'CAPTURE_UNREADABLE', 'file': path.name, 'detail': str(exc)})
    return items


def write_run_diagnostics(result: GameTestResult, *, journal_path: Path | None = None) -> dict:
    """Explain existing evidence and gaps; never upgrade or mutate a result."""
    if not result.run_dir:
        return {}
    root = Path(result.run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    gaps: list[dict] = []
    coverage = _load(root/'path-coverage.json', gaps, 'path-coverage.json')
    samples = _load(root/'sample-catalog.json', gaps, 'sample-catalog.json')
    from tester_spin.run_tree import write_run_tree
    tree = write_run_tree(result)
    attempts = []
    for attempt_index, attempt in enumerate(result.attempts):
        evidence = _evidence(root, Path(attempt.artifact_dir), gaps) if attempt.artifact_dir else []
        if not evidence:
            gaps.append({'code': 'ATTEMPT_EVIDENCE_MISSING', 'attempt': attempt.number})
        requests = [e['path'] for e in evidence if e['kind'] == 'request']
        responses = [e['path'] for e in evidence if e['kind'] == 'response']
        envelopes = [e['path'] for e in evidence if e['kind'] == 'envelope']
        trajectory = tree['trajectories'][attempt_index]
        for detail in trajectory.get('gaps', []):
            gaps.append({'code': 'TRAJECTORY_SEQUENCE_GAP', 'attempt': attempt.number,
                         'trajectory_id': trajectory['id'], 'detail': detail})
        if trajectory['sequence_status'] != 'UNRESOLVED':
            requests = [s['request'][0]['path'] for s in trajectory['steps'] if s['request']]
            responses = [s['response'][0]['path'] for s in trajectory['steps'] if s['response']]
        else:
            requests, responses = [], []
            gaps.append({'code': 'CAPTURE_ORDER_UNRESOLVED', 'attempt': attempt.number})
        if not requests or not responses:
            gaps.append({'code': 'SEPARATE_WIRE_PAIR_UNAVAILABLE', 'attempt': attempt.number,
                         'detail': 'Request/response may be embedded in envelope; no invented pairing.', 'envelopes': envelopes})
        attempts.append({'return_to_base': trajectory.get('return_to_base', {}), 'number': attempt.number, 'mode_id': attempt.mode_id,
                         'reported_ok': attempt.ok, 'reported_terminal': attempt.terminal,
                         'http_status': attempt.status_code, 'last_state': attempt.na,
                         'wire_steps': attempt.wire_steps, 'elapsed_ms': attempt.elapsed_ms,
                         'error': attempt.error, 'warning': attempt.warning, 'evidence': evidence,
                         'first_request': requests[0] if requests else None,
                         'last_request': requests[-1] if requests else None,
                         'last_response': responses[-1] if responses else None,
                         'ordering': trajectory['sequence_status'], 'trajectory_id': trajectory['id'],
                         'sequence_complete': trajectory.get('offline_replay_ready', False),
                         'sequence_gaps': trajectory.get('gaps', [])})
    known = {str(m.get('id')): m for m in result.discovered_modes}
    for attempt in result.attempts:
        known.setdefault(attempt.mode_id, {'id': attempt.mode_id, 'kind': attempt.mode_kind})
    modes = []
    unknown = []
    unresolved = [m for m in result.discovered_modes if m.get('executable') is False or m.get('observed') is False or 'UNRESOLVED' in str(m.get('kind', ''))]
    for mid, metadata in known.items():
        runs = [a for a in attempts if a['mode_id'] == mid]
        branches = [b for b in coverage.get('branch_points', []) if b.get('mode_id') == mid]
        missing = [v for b in branches for v in b.get('missing', [])]
        terminal = [a for a in runs if a['reported_ok'] and a['reported_terminal'] and not a['error'] and not a['warning']]
        # Shared unresolved observations have no proven association with a particular mode.
        # Be conservative until a provider supplies that association.
        validated = bool(runs) and len(terminal) == len(runs) and not missing and all(b.get('complete') for b in branches) and not unresolved
        validated = validated and all(a['evidence'] for a in runs)
        validated = validated and bool(coverage.get('complete')) and bool(samples.get('observed_paths_sampled'))
        validated = validated and all(a['last_request'] and a['last_response'] for a in runs)
        validated = validated and all(a['sequence_complete'] for a in runs)
        validated = validated and all(not a.get('return_to_base') or a['return_to_base'].get('status') == 'CONFIRMED' for a in runs)
        status = 'VALIDATED' if validated else 'INCOMPLETE' if runs else 'DISCOVERED'
        modes.append({'id': mid, 'kind': metadata.get('kind'), 'status': status, 'validated': bool(validated),
                      'tested': bool(runs), 'attempt_count': len(runs), 'terminal_count': len(terminal),
                      'missing_options': missing, 'branches': branches, 'provider_metadata': metadata})
    for metadata in unresolved:
        neutral = sanitize({'provider': result.provider, 'observation': metadata})
        fingerprint = hashlib.sha256(json.dumps(neutral, sort_keys=True, default=str).encode()).hexdigest()
        unknown.append({'id': 'UNCLASSIFIED_WIRE_VARIANT_' + fingerprint[:16],
                        'signature_scope': 'provider-reported unresolved observation; not a semantic classification',
                        'observation': neutral['observation'], 'evidence': [a['evidence'] for a in attempts]})
    comparisons = []
    baseline = next((a for a in attempts if a['mode_id'] == 'SPIN' and a['first_request']), None)
    if baseline:
        seen = set()
        for a in attempts:
            if a['mode_id'] == 'SPIN' or a['mode_id'] in seen or not a['first_request']:
                continue
            seen.add(a['mode_id'])
            try:
                diff = compare_captures(root/baseline['first_request'], root/a['first_request'])
                comparisons.append({'before_mode': 'SPIN', 'after_mode': a['mode_id'],
                                    'before_capture': baseline['first_request'], 'after_capture': a['first_request'], **diff})
            except (OSError, ValueError, UnicodeError) as exc:
                gaps.append({'code': 'COMPARISON_UNAVAILABLE', 'mode': a['mode_id'], 'detail': str(exc)})
    bootstrap = []
    for directory in (root/'bootstrap', root/'discovery'):
        if directory.is_dir():
            bootstrap.extend(_evidence(root, directory, gaps))
    # Keep root-level init/error envelopes visible, without re-scanning attempts or assets.
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix == '.json' and any(t in path.name for t in ('bootstrap', 'init', 'error')):
            bootstrap.append({'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size, 'kind': 'envelope'})
    next_steps = []
    if unknown or any(not b.get('complete') for b in coverage.get('branch_points', [])):
        next_steps.append('Revisar la respuesta que anuncia la acción/opción pendiente y el serializer del cliente de este proveedor. No inventar argumentos ni un handler.')
    if result.error or any(a['error'] for a in attempts):
        next_steps.append('Comparar la última request y response con un intento válido del mismo juego. El error observado no demuestra por sí solo la causa.')
    if gaps:
        next_steps.append('Resolver los huecos de evidencia indicados antes de atribuir el fallo al servidor o al juego.')
    if not next_steps:
        next_steps.append('Las rutas observadas terminaron; una muestra corta no prueba ausencia de otras compras o estados naturales.')
    report = sanitize({'schema': 'tester-spin/run-diagnostics/v1', 'provider': result.provider,
                       'game': {'slug': result.slug, 'name': result.game_name, 'symbol': result.symbol},
                       'started_at': result.started_at, 'finished_at': result.finished_at,
                       'result_status': result.status, 'scope': 'observed_paths_only',
                       'observed_error': result.error,
                       'root_cause': {'status': 'UNDETERMINED', 'reason': 'La captura documenta hechos; la causa requiere análisis y contraste.'},
                       'modes': modes, 'attempts': attempts, 'bootstrap_evidence': bootstrap,
                       'unknown_actions': unknown, 'request_comparisons': comparisons,
                       'coverage': coverage, 'sample_diagnostics': samples.get('diagnostics', []),
                       'evidence_gaps': gaps, 'next_steps': next_steps,
                       'journal': str(journal_path) if journal_path else None,
                       'tree': 'run-tree.html', 'tree_data': 'run-tree.json'})
    _write_report(root, report)
    return report


def _write_report(root: Path, report: dict) -> None:
    (root/'diagnostic.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [f"# Diagnóstico — {report['game']['name']}", '',
             f"Proveedor: {report['provider']} · Resultado: {report['result_status']}", '',
             '**Alcance:** rutas observadas. No certifica descubrimiento exhaustivo.', '',
             '## Qué ocurrió', '', report['observed_error'] or 'Sin error global registrado; revisar cobertura y estados por acción.', '',
             'Causa: **no determinada automáticamente**. Un HTTP 200 no demuestra cierre terminal.', '',
             '## Acciones', '', '| Acción | Estado | Intentos | Terminales | Opciones pendientes |',
             '|---|---|---:|---:|---|']
    for mode in report['modes']:
        lines.append(f"| {mode['id']} | {mode['status']} | {mode['attempt_count']} | {mode['terminal_count']} | {mode['missing_options']} |")
    lines += ['', '## Último paso por intento', '']
    for attempt in report['attempts']:
        lines += [f"### {attempt['mode_id']} · intento {attempt['number']}", '',
                  f"HTTP: {attempt['http_status']} · estado registrado: `{attempt['last_state']}` · terminal informado: {attempt['reported_terminal']}", '',
                  f"Error: {attempt['error'] or 'ninguno registrado'}", '',
                  f"Advertencia: {attempt['warning'] or 'ninguna registrada'}", '']
        if attempt.get('return_to_base'):
            proof = attempt['return_to_base']
            lines += [f"Regreso al juego base: **{proof.get('status')}** · confirmaciones consecutivas: {proof.get('consecutive_base', 0)}/{proof.get('required', 2)}", '']
        for key, label in [('last_request', 'Última request'), ('last_response', 'Última response')]:
            path = attempt[key]
            lines.append(f"- {label}: [{path}](<{path}>)" if path else f'- {label}: sin captura separada; consultar envelopes y huecos de evidencia.')
        for e in attempt['evidence']:
            if e['kind'] == 'envelope':
                lines.append(f"- Envelope: [{e['path']}](<{e['path']}>)")
        lines.append('')
    lines += ['## Qué investigar', ''] + ['- ' + item for item in report['next_steps']]
    lines += ['', '## Huecos de evidencia', '']
    lines += ['- ' + json.dumps(gap, ensure_ascii=False) for gap in report['evidence_gaps']] or ['Ninguno en los índices revisados.']
    lines += ['', '## Comparación de requests', '', 'Diferencias literales: no prueban causalidad. Las credenciales están ocultas.', '']
    for diff in report['request_comparisons']:
        lines += [f"### {diff['before_mode']} → {diff['after_mode']}", '', '```json', json.dumps(diff['differences'], ensure_ascii=False, indent=2), '```', '']
    lines += ['', '[Respuestas distintas del servidor y revisión pendiente](server-observations.md)', '', '[Índice completo, hashes, compras y observaciones desconocidas](diagnostic.json)',
              '', '[Árbol de tiradas y origen de cada recorrido](run-tree.html)',
              '', '[Cobertura de opciones](path-coverage.json) · [Catálogo de muestras](sample-catalog.json)', '']
    if report['journal']:
        lines += [f"Registro cronológico: {report['journal']}", '']
    (root/'diagnostic.md').write_text('\n'.join(lines), encoding='utf-8')
