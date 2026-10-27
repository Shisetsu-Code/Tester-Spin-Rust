"""Origin-preserving paths and verified offline replay; no remote execution."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path

from tester_spin.models import GameTestResult
from tester_spin.run_diagnostics import _evidence, _read_capture, sanitize


def _pairs(root: Path, attempt_dir: Path, metadata: dict) -> tuple[list, str, list]:
    gaps = []
    evidence = _evidence(root, attempt_dir, gaps)
    pairs = {}
    for item in evidence:
        if item['kind'] not in {'request', 'response'}:
            continue
        path = Path(item['path'])
        local_parts = (root/path).relative_to(attempt_dir.resolve()).parts
        if any(part in {'bootstrap', 'discovery', 'return-to-base'} for part in local_parts[:-1]):
            continue
        stem = path.stem
        match = re.fullmatch(r'(.*?)[.-](request|response)(?:\.raw)?', stem)
        if match:
            label = match[1]
        elif stem in {'request', 'response'}:
            label = 'entry'
        elif match := re.fullmatch(r'(request|response)-(\d+)(?:\.raw)?', stem):
            # GPAS records entry, then request-1/response-1, request-2/response-2.
            # These are subsequent exchanges, even if their bytes equal entry.
            label = 'exchange-' + match[2]
        else:
            continue
        key = (path.parent.as_posix(), label)
        pair = pairs.setdefault(key, {'label': label, 'directory': key[0], 'request': [], 'response': []})
        pair[item['kind']].append(item)
    steps = list(pairs.values())
    numbered = [(int(match[1]), step) for step in steps
                if (match := re.search(r'(?:^|[-_])step[-_](\d+)', step['label']))]
    entry = next((s for s in steps if s['label'] == 'entry'), None)
    if entry and numbered:
        first = min(numbered, key=lambda pair: pair[0])[1]
        if entry['directory'] == first['directory'] and all(
            {e['sha256'] for e in entry[d]} & {e['sha256'] for e in first[d]}
            for d in ('request', 'response')
        ):
            for direction in ('request', 'response'):
                first[direction].extend(entry[direction])
            steps.remove(entry)
    declared = metadata.get('state_machine', [])
    parents = {step['directory'] for step in steps}
    numbers = []
    for step in steps:
        match = re.search(r'(?:^|[-_])(?:step[-_]|exchange-)(\d+)', step['label'])
        numbers.append(int(match[1]) if match else -1 if step['label'] == 'entry' else None)
    if steps and len(parents) == 1 and all(n is not None for n in numbers) and len(set(numbers)) == len(numbers):
        steps = [step for _, step in sorted(zip(numbers, steps), key=lambda pair: pair[0])]
        ordering = 'ARTIFACT_STEP_INDEX'
        nonnegative = sorted(n for n in numbers if n >= 0)
        allowed_starts = {0, 1, 2} if -1 in numbers else {0, 1}
        if any(re.fullmatch(r'exchange-\d+', step['label']) for step in steps):
            allowed_starts = {1} if -1 in numbers else {0}
        if nonnegative and (nonnegative[0] not in allowed_starts or nonnegative != list(range(nonnegative[0], nonnegative[-1]+1))):
            gaps.append('Missing step indices: complete offline replay is not proven.')
    elif steps and len(parents) == 1 and isinstance(declared, list) and declared and all(s['label'] in declared for s in steps):
        steps.sort(key=lambda s: declared.index(s['label']))
        ordering = 'PROVIDER_DECLARED_STATE_MACHINE'
    elif len(steps) == 1:
        ordering = 'SINGLE_EXCHANGE'
    else:
        ordering = 'UNRESOLVED'
        gaps.append('Capture ordering is not proven; no sequential edges invented.')
    for step in steps:
        for direction in ('request', 'response'):
            step[direction].sort(key=lambda e: (not e['path'].endswith('.json'), e['path']))
        if not step['request'] or not step['response']:
            gaps.append(f"Missing request/response pair: {step['label']}")
    return steps, ordering, gaps


def _frames(root: Path, attempt_dir: Path) -> tuple[list, list]:
    gaps = []
    for evidence in _evidence(root, attempt_dir, gaps):
        if evidence['kind'] != 'envelope' or not evidence['path'].endswith('.json'):
            continue
        try:
            value = _read_capture(root/evidence['path'])
        except (OSError, ValueError, UnicodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get('frames'), list):
            events = []
            for index, frame in enumerate(value['frames']):
                if not isinstance(frame, dict) or 'direction' not in frame or 'payload' not in frame:
                    gaps.append('Frame lacks explicit direction/payload')
                    continue
                if isinstance(frame['payload'], dict) and frame['payload'].get('truncated'):
                    gaps.append('Truncated frame cannot be replayed completely')
                events.append({'index': index, 'direction': frame['direction'], 'payload': frame['payload'],
                               'recorded_classification': frame.get('classification'), 'evidence': evidence})
            return events, gaps
    return [], gaps


def write_run_tree(result: GameTestResult) -> dict:
    root = Path(result.run_dir).resolve()
    metadata = {str(m.get('id')): m for m in result.discovered_modes}
    trajectories = []
    for index, attempt in enumerate(result.attempts):
        origin = {'mode_id': attempt.mode_id, 'kind': attempt.mode_kind,
                  'provider_metadata': metadata.get(attempt.mode_id, {})}
        identity = json.dumps([result.provider, result.slug, attempt.mode_id, attempt.number, index], ensure_ascii=False)
        tid = hashlib.sha256(identity.encode()).hexdigest()[:20]
        steps, ordering, gaps = _pairs(root, Path(attempt.artifact_dir), metadata.get(attempt.mode_id, {})) if attempt.artifact_dir else ([], 'UNRESOLVED', ['Missing attempt directory'])
        events = []
        if result.provider == 'playtech' and metadata.get(attempt.mode_id, {}).get('execution_scope') == 'official-local-demo':
            from tester_spin.providers.playtech.ngm_capture import local_capture_gaps
            directory = Path(attempt.artifact_dir).resolve()
            if directory.is_relative_to(root):
                gaps.extend(local_capture_gaps(directory, attempt.wire_steps, _read_capture))
            else:
                gaps.append('NGM_LOCAL_EVIDENCE_OUTSIDE_RUN')
        if attempt.wire_steps and steps and len(steps) != attempt.wire_steps:
            gaps.append(f'Captured exchanges={len(steps)}; executor reported wire_steps={attempt.wire_steps}.')
        if not steps and attempt.artifact_dir:
            events, frame_gaps = _frames(root, Path(attempt.artifact_dir))
            if events:
                ordering, gaps = 'RECORDED_FRAME_ARRAY', frame_gaps
                for n, event in enumerate(events):
                    event['id'] = f'{tid}:frame:{n}'
                    event['parent_id'] = tid if n == 0 else f'{tid}:frame:{n-1}'
        parent = tid
        for n, step in enumerate(steps):
            step['id'] = f'{tid}:{n}'
            step['parent_id'] = parent if ordering != 'UNRESOLVED' else tid
            parent = step['id']
            step['observed_response'] = None
            if step['response']:
                try:
                    step['observed_response'] = _read_capture(root/step['response'][0]['path'])
                except (OSError, ValueError, UnicodeError) as exc:
                    gaps.append(f"Response cannot be decoded for display: {step['label']}: {exc}")
        proof = {}
        if attempt.artifact_dir:
            try:
                proof_path = Path(attempt.artifact_dir).resolve()/'return-to-base.json'
                if proof_path.is_relative_to(root):
                    proof = json.loads(proof_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        capture_directory = str(Path(attempt.artifact_dir).resolve().relative_to(root)) if attempt.artifact_dir and Path(attempt.artifact_dir).resolve().is_relative_to(root) else None
        proof_evidence = {'path': proof_path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(proof_path.read_bytes()).hexdigest()} if proof else None
        trajectories.append({'capture_directory': capture_directory, 'return_to_base': proof, 'return_to_base_evidence': proof_evidence, 'id': tid, 'origin': origin, 'attempt': attempt.number,
                             'reported_terminal': attempt.terminal, 'reported_ok': attempt.ok,
                             'sequence_status': ordering, 'steps': steps, 'events': events, 'gaps': gaps,
                             'offline_replay_ready': bool(steps or events) and ordering != 'UNRESOLVED' and not gaps})
    coverage = {}
    try:
        coverage = json.loads((root/'path-coverage.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    tree = sanitize({'schema': 'tester-spin/run-tree/v1', 'provider': result.provider,
                     'game': result.slug, 'scope': 'observed_trajectories',
                     'exact_remote_outcome_reproducible': False,
                     'remote_replay_note': 'No se envían requests. La repetición del premio aleatorio no está demostrada.',
                     'trajectories': trajectories, 'announced_branches': coverage.get('branch_points', [])})
    root.mkdir(parents=True, exist_ok=True)
    (root/'run-tree.json').write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
    from tester_spin.server_observations import write_observations
    write_observations(root, tree)
    _render(root, tree, result.game_name)
    return tree


def replay_capture(tree_path: Path, trajectory_id: str) -> dict:
    """Read a recorded path, checking every source file before returning its data."""
    tree_path = Path(tree_path).resolve()
    root = tree_path.parent
    tree = json.loads(tree_path.read_text(encoding='utf-8'))
    trajectory = next(p for p in tree['trajectories'] if p['id'] == trajectory_id)
    if not trajectory['offline_replay_ready']:
        raise ValueError('Sequence incomplete or ordering unresolved; replay is unavailable')
    steps = []
    replayed_events = []
    verified_envelopes = {}
    for event in trajectory.get('events', []):
        entry = event['evidence']
        source = (root/entry['path']).resolve()
        if not source.is_relative_to(root) or hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Capture hash integrity mismatch')
        if source not in verified_envelopes:
            verified_envelopes[source] = _read_capture(source)
        frame = verified_envelopes[source]['frames'][event['index']]
        replayed_events.append({'index': event['index'], **frame})
    for step in trajectory['steps']:
        decoded = {}
        for direction in ('request', 'response'):
            entries = step[direction]
            for entry in entries:
                source = (root/entry['path']).resolve()
                if not source.is_relative_to(root):
                    raise ValueError('Capture outside run root')
                if hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
                    raise ValueError('Capture hash integrity mismatch: ' + entry['path'])
            decoded[direction] = _read_capture(root/entries[0]['path'])
        steps.append({'id': step['id'], 'label': step['label'], **decoded})
    closure = None
    proof = trajectory.get('return_to_base_evidence')
    if proof:
        source = (root/proof['path']).resolve()
        if not source.is_relative_to(root) or hashlib.sha256(source.read_bytes()).hexdigest() != proof['sha256']:
            raise ValueError('Closure capture integrity mismatch')
        closure = _read_capture(source)
    return {'provider': tree['provider'], 'game': tree['game'], 'origin': trajectory['origin'],
            'replay': 'OFFLINE_CAPTURE_ONLY', 'steps': steps, 'events': replayed_events, 'return_to_base': closure}


def _render(root: Path, tree: dict, name: str) -> None:
    esc = lambda value: html.escape(str(value), quote=True)
    parts = ['<!doctype html><html lang="es"><meta charset="utf-8"><title>Árbol de tiradas</title>',
             '<style>body{font:15px system-ui;margin:32px;max-width:1200px;color:#18232e}details{margin:12px 0 12px 20px;border-left:3px solid #bacadb;padding:8px 16px}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f4f8;padding:12px}a{color:#175c9e}</style>',
             '<h1>Árbol de tiradas — '+esc(name)+'</h1>',
             '<p>Cada recorrido conserva su entrada y sus capturas. Las respuestas se muestran con sus campos originales, sin inventar nombres de funciones.</p>',
             '<p>Reproducción de captura: local y verificable. Repetir el mismo premio aleatorio en el servidor no está demostrado.</p>',
             '<p><a href="server-observations.md">Respuestas nuevas</a> · <a href="diagnostic.md">Diagnóstico</a> · <a href="run-tree.json">Árbol completo</a></p>']
    for path in tree['trajectories']:
        parts.append('<details><summary>'+esc(path['origin']['mode_id'])+' → intento '+str(path['attempt'])+' · '+esc(path['sequence_status'])+'</summary>')
        parts.append('<p>ID para reproducción: <code>'+esc(path['id'])+'</code></p>')
        parts.append('<p>Origen: <code>'+esc(json.dumps(path['origin'], ensure_ascii=False))+'</code></p>')
        for step in path['steps']:
            parts.append('<details><summary>'+esc(step['label'])+'</summary>')
            for direction in ('request', 'response'):
                for item in step[direction]:
                    parts.append('<p><a href="'+esc(item['path'])+'">'+esc(direction+': '+item['path'])+'</a></p>')
            parts.append('<pre>'+esc(json.dumps(step['observed_response'], ensure_ascii=False, indent=2))+'</pre></details>')
        for event in path.get('events', []):
            parts.append('<details><summary>Frame '+str(event['index'])+' · '+esc(event['direction'])+'</summary><pre>'+esc(json.dumps(event['payload'], ensure_ascii=False, indent=2))+'</pre></details>')
        if path.get('return_to_base'):
            proof = path['return_to_base']
            parts.append('<details><summary>Regreso al juego base: '+esc(proof.get('status'))+'</summary><pre>'+esc(json.dumps(proof, ensure_ascii=False, indent=2))+'</pre></details>')
        if path['gaps']:
            parts.append('<pre>Pendiente: '+esc(json.dumps(path['gaps'], ensure_ascii=False, indent=2))+'</pre>')
        parts.append('</details>')
    parts.append('<h2>Opciones anunciadas y cobertura</h2><pre>'+esc(json.dumps(tree['announced_branches'], ensure_ascii=False, indent=2))+'</pre></html>')
    (root/'run-tree.html').write_text(''.join(parts), encoding='utf-8')


def latest_run_report(game_root: Path) -> Path | None:
    root = Path(game_root).resolve()
    candidates = [p.resolve() for folder in (root/'tests', root/'diagnostics')
                  if folder.is_dir() for p in folder.rglob('run-tree.html')
                  if p.is_file() and p.resolve().is_relative_to(root)]
    return max(candidates, key=lambda p: p.stat().st_mtime_ns, default=None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reproduce una captura local; nunca envía requests.')
    parser.add_argument('tree', type=Path)
    parser.add_argument('trajectory')
    args = parser.parse_args()
    print(json.dumps(replay_capture(args.tree, args.trajectory), ensure_ascii=False, indent=2))
