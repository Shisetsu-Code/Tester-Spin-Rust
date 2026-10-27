"""Passive, per-game response novelty. Observed does not mean understood."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from contextvars import ContextVar
from datetime import datetime, timezone

_directory = ContextVar('response_capture_directory', default=None)
_observer = ContextVar('live_response_observer', default=None)


def reset_live_observer():
    _directory.set(None)
    _observer.set(ResponseObserver('current-game'))


def set_capture_directory(path):
    previous = _directory.get()
    _directory.set(Path(path) if path is not None else None)
    return previous


def observe_live(payload, *, action, request=None, status=None):
    from tester_spin.return_to_base import audit_enabled
    from tester_spin.run_diagnostics import sanitize
    directory = _directory.get()
    if not audit_enabled() or directory is None:
        return
    observer = _observer.get()
    if observer is None:
        observer = ResponseObserver('current-game')
        _observer.set(observer)
    clean = sanitize(payload)
    item = observer.observe(clean, action=str(action))
    item.update(action=str(action), response=clean, request=sanitize(request), http_status=status,
                captured_at=datetime.now(timezone.utc).isoformat())
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'server-responses.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(item, ensure_ascii=False)+'\n')


def observe_http(response, *, action='response', request=None):
    from tester_spin.return_to_base import audit_enabled
    if not audit_enabled() or _directory.get() is None:
        return
    try:
        payload = response.json()
    except (ValueError, TypeError):
        text = response.text
        if '=' in text and '<' not in text:
            from urllib.parse import parse_qsl
            payload = dict(parse_qsl(text, keep_blank_values=True))
        else:
            payload = text
    observe_live(payload, action=action, request=request, status=response.status_code)

# Protocol field names, never game names. Values outside these fields are typed,
# not fingerprinted: a new win, balance or random symbol is not a new event.
STATE_FIELDS = frozenset({
    'st', 'type', 'na', 'state', 'status', 'action', 'next_action', 'nextaction',
    'available_actions', 'availableactions', 'phasecur', 'phasenext', 'mode',
    'spinmode', 'spinmodes', 'choices', 'available', 'options_available',
    'success', 'error', 'errorcode', 'code', 'command', 'event', 'eventtype',
    'final', 'nextaction', 'selected', 'choice', 'available_commands',
    'hasstate', 'has_state', 'gamemode', 'game_mode', 'spin_mode', 'spin_modes',
})


def _shape(value, path='', state=False, provider=None):
    result = {}
    if isinstance(value, dict):
        result[path] = 'object'
        for key, item in sorted(value.items()):
            escaped = str(key).replace('~', '~0').replace('/', '~1')
            item_state = str(key).lower() in STATE_FIELDS
            if provider == 'ka_gaming' and path == '/md':
                # KA st is the reel screen, unlike scalar state codes elsewhere.
                if key == 'st' and isinstance(item, list):
                    item_state = False
                elif key in {'fs', 'rf', 'acb', 'mb', 'fsr'}:
                    item_state = True
            result.update(_shape(item, path+'/'+escaped, item_state, provider))
    elif isinstance(value, list):
        result[path] = 'array'
        # Union shapes across every element; array length and ordering are noise.
        shapes = [_shape(item, path+'/*', state, provider) for item in value]
        for key in sorted({key for shape in shapes for key in shape}):
            result[key] = sorted({json.dumps(shape[key], sort_keys=True) for shape in shapes if key in shape})
    else:
        kind = 'null' if value is None else 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'string'
        result[path] = {'type': kind, 'value': value} if state else kind
    return result


def change_kind(paths):
    outcome_prefixes = ('/outcome/wins', '/outcome/special_symbols', '/outcome/screen')
    def outcome_only(path):
        parts = [part.casefold() for part in path.split('/')]
        if any(part in STATE_FIELDS for part in parts):
            return False
        for prefix in outcome_prefixes:
            if not path.startswith(prefix + '/'):
                continue
            children = path[len(prefix) + 1:].split('/')
            if prefix == '/outcome/special_symbols':
                if children[0] not in {'wild', 'scatter'}:
                    return False
                children = children[1:]
            return bool(children) and all(part == '*' or part.isdecimal() for part in children)
        return False
    return 'OUTCOME_VARIATION' if paths and all(outcome_only(path) for path in paths) else 'PROTOCOL_CHANGE'


class ResponseObserver:
    def __init__(self, provider):
        self.provider = provider
        self.baselines = {}
        self.seen = {}

    def observe(self, payload, *, action):
        if not isinstance(payload, (dict, list)):
            return {'classification': 'UNPARSED', 'changed_paths': [], 'review_required': True}
        shape = _shape(payload, provider=self.provider)
        signature = hashlib.sha256(json.dumps(shape, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        seen = self.seen.setdefault(action, set())
        baseline = self.baselines.get(action)
        classification = 'BASELINE' if baseline is None else 'SEEN' if signature in seen else 'NEW_RESPONSE'
        changed = [] if baseline is None else sorted(k for k in set(shape) | set(baseline) if shape.get(k) != baseline.get(k))
        self.baselines.setdefault(action, shape)
        seen.add(signature)
        kind = change_kind(changed) if classification == 'NEW_RESPONSE' else 'REFERENCE'
        return {'change_kind': kind, 'classification': classification, 'signature': signature,
                'changed_paths': changed if classification == 'NEW_RESPONSE' else [],
                'review_required': classification == 'NEW_RESPONSE' and kind != 'OUTCOME_VARIATION'}


def write_observations(root: Path, tree: dict):
    from tester_spin.run_diagnostics import _read_capture, sanitize
    observer = ResponseObserver(tree['provider'])
    records = []

    def record(payload, action, trajectory, source):
        item = observer.observe(payload, action=action)
        records.append(dict(item, action=action, trajectory_id=trajectory['id'],
                            origin=trajectory['origin'], source=source))

    def action_of(request):
        if isinstance(request, dict):
            for key in ('action', 'command', 'q', 'type'):
                if key in request:
                    return str(request[key])
            for key in ('data', 'body', 'payload', 'form', 'fields'):
                if isinstance(request.get(key), dict):
                    found = action_of(request[key])
                    if found != 'response':
                        return found
        return 'response'

    for trajectory in tree['trajectories']:
        for step in trajectory['steps']:
            request = None
            if step['request']:
                try:
                    request = _read_capture(root/step['request'][0]['path'])
                except (OSError, ValueError, UnicodeError):
                    pass
            record(step.get('observed_response'), action_of(request), trajectory,
                   step['response'][0]['path'] if step['response'] else step['id'])
        for event in trajectory['events']:
            if event['direction'] != 'received':
                continue
            payload = event['payload']
            if isinstance(payload, dict) and payload.get('kind') == 'text':
                raw = str(payload.get('text', ''))
                # D1 wraps JSON with a transport prefix. Never execute payloads.
                try:
                    payload = json.loads(raw[raw.index('{'):])
                except (ValueError, TypeError):
                    payload = raw
            record(payload, 'ws:'+str(payload.get('type', 'unknown')) if isinstance(payload, dict) else 'ws', trajectory,
                   event['evidence']['path']+'#frame='+str(event['index']))
        proof = trajectory.get('return_to_base') or {}
        for probe in proof.get('probes', []):
            for capture in probe.get('captures', []):
                record(capture.get('response'), action_of(capture.get('request')), trajectory,
                       probe.get('directory', '')+'#'+str(capture.get('step', 0)))
    # Prefer live observations: they include rejected HTTP bodies that never
    # reached a provider's normal success-capture path.
    live_records = []
    for trajectory in tree['trajectories']:
        capture_dir = trajectory.get('capture_directory')
        if not capture_dir:
            continue
        directory = (root/capture_dir).resolve()
        if not directory.is_relative_to(root.resolve()):
            continue
        for trace in sorted(directory.rglob('server-responses.jsonl')):
            if not trace.resolve().is_relative_to(root.resolve()):
                continue
            for number, line in enumerate(trace.read_text(encoding='utf-8').splitlines(), 1):
                try:
                    entry = json.loads(line)
                except ValueError:
                    entry = {'classification': 'UNPARSED', 'review_required': True, 'changed_paths': [], 'action': 'unknown'}
                entry.pop('response', None)
                entry.pop('request', None)
                live_records.append(dict(entry, trajectory_id=trajectory['id'], origin=trajectory['origin'],
                                         source=trace.relative_to(root).as_posix()+'#line='+str(number)))
    if live_records:
        live_trajectories = {item["trajectory_id"] for item in live_records}
        records = [item for item in records if item["trajectory_id"] not in live_trajectories] + live_records
    for item in records:
        if item.get('classification') == 'NEW_RESPONSE':
            item['change_kind'] = change_kind(item.get('changed_paths', []))
            item['review_required'] = item['change_kind'] != 'OUTCOME_VARIATION'
    pending = [item for item in tree.get('announced_branches', []) if item.get('missing')]
    report = sanitize({'schema': 'tester-spin/server-observations/v1', 'provider': tree['provider'],
                       'scope': 'this_game_this_run', 'baseline_is_not_contract': True,
                       'new_responses': sum(r['classification'] == 'NEW_RESPONSE' for r in records),
                       'protocol_changes': sum(r.get('change_kind') == 'PROTOCOL_CHANGE' for r in records),
                       'outcome_variations': sum(r.get('change_kind') == 'OUTCOME_VARIATION' for r in records),
                       'unparsed': sum(r['classification'] == 'UNPARSED' for r in records),
                       'pending_branches': len(pending),
                       'pending_options': sum(len(item['missing']) for item in pending),
                       'coverage_pending': pending,
                       'observations': records})
    (root/'server-observations.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Respuestas del servidor', '',
             'Una respuesta distinta es una candidata para revisión, no un evento confirmado. La primera respuesta de cada acción es una referencia observada, no un contrato validado.', '',
             f"Novedades de protocolo: {report['protocol_changes']} · Variaciones de resultado: {report['outcome_variations']} · Respuestas no legibles: {report['unparsed']} · Pendientes de cobertura: {report['pending_branches']}", '']
    for branch in pending:
        lines += [f"- {branch['mode_id']}: faltan {', '.join(map(str, branch['missing']))}."]
    for item in records:
        if item['review_required']:
            lines += [f"## {item['origin']['mode_id']} · {item['action']}", '',
                      f"Captura: {item['source']}", '',
                      'Campos distintos: '+', '.join(item['changed_paths']), '']
    lines += ['[Detalle y origen de cada observación](server-observations.json)', '', '[Árbol](run-tree.html)']
    (root/'server-observations.md').write_text('\n'.join(lines), encoding='utf-8')
    return report
