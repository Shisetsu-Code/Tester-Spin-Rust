"""Safe capture inventory, separate from static contracts and verified rounds.

Only counts and fixed descriptions leave this module. Raw URLs and payloads may
contain session credentials and are never copied into the diagnostic report.
"""
import json
from urllib.parse import urlsplit
from tester_spin.har_capture_diagnostics import capture_entries


def _frame_kind(url, frame):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return 'unclassified'
    if (parsed.hostname != 'oapi.playtechhorizon.com' or
            not parsed.path.startswith('/socket.io/') or parsed.scheme != 'wss'):
        return 'unclassified'
    opcode = frame.get('opcode', 1)
    payload = frame.get('payloadData', frame.get('data', frame.get('payload')))
    direction = frame.get('direction', frame.get('type'))
    direction = {'send':'sent', 'receive':'received'}.get(direction, direction)
    if opcode != 1 or direction not in ('sent', 'received') or not isinstance(payload, str):
        return 'unclassified'
    if payload in ('0::', '1::', '2::'):
        return 'control'
    if not payload.startswith('3:::') or len(payload) > 100_000:
        return 'unclassified'
    try:
        data = json.loads(payload[4:])
    except (ValueError, RecursionError):
        return 'unclassified'
    if not isinstance(data, dict):
        return 'unclassified'
    if (direction == 'sent' and data.get('ID') == 35844 and
            isinstance(data.get('urlTypeList'), list) and
            set(data) <= {'ID','umid','urlTypeList','casinoName','customParameters',
                          'clientSkinName','clientPlatform','clientType','languageCode'}):
        return 'navigation'
    if (direction == 'received' and data.get('ID') == 35845 and set(data) <= {'ID','umid','data'} and
            isinstance(data.get('data'), dict) and set(data['data']) == {'urlList'} and
            isinstance(data['data']['urlList'], list)):
        return 'navigation'
    return 'unclassified'


def capture_diagnostics(document):
    entries = capture_entries(document)
    counts = dict(control=0, navigation=0, unclassified=0)
    issues, formats = [], []
    # Prefer one representation per connection; some exporters write both.
    for entry in entries:
        for key in ('_webSocketFrames', '_webSocketMessages'):
            frames = entry.get(key)
            if isinstance(frames, list) and frames:
                formats.append(key)
                for frame in frames:
                    kind = _frame_kind(entry.get('request', {}).get('url', ''), frame) if isinstance(frame, dict) else 'unclassified'
                    counts[kind] += 1
                break
    # The legacy Tester writer keeps frames at log level instead of entries.
    if not formats:
        frames = document['log'].get('_warpWebSockets', [])
        if isinstance(frames, list) and frames:
            formats.append('_warpWebSockets')
            for frame in frames:
                kind = _frame_kind(frame.get('url', ''), frame) if isinstance(frame, dict) else 'unclassified'
                counts[kind] += 1
    total = sum(counts.values())
    if not entries and not total:
        issues.append('HAR_EMPTY_CAPTURE')
    elif total and not counts['unclassified']:
        issues.append('HAR_ONLY_LOBBY_WEBSOCKET_TRAFFIC')
    steps = []
    if 'HAR_EMPTY_CAPTURE' in issues:
        steps.append('La captura está vacía. Iniciá la grabación antes de recargar la demo, conservá el registro y exportá con contenido después de cerrar la ronda.')
    if 'HAR_ONLY_LOBBY_WEBSOCKET_TRAFFIC' in issues:
        steps.append('Las tramas capturadas solo muestran conexión, navegación del lobby o desconexión; no aportan evidencia de una ronda.')
    steps.append('NGM offline ejecuta dentro del cliente: conservá ngm-events.jsonl y los resúmenes por intento de una prueba nueva en Tester-Spin para verificar apuesta, premio, saldo y cierre. El HAR por sí solo no valida esas rondas.')
    return dict(entry_count=len(entries), websocket_frame_count=total,
                websocket_control_count=counts['control'], websocket_navigation_count=counts['navigation'],
                websocket_unclassified_count=counts['unclassified'], websocket_formats=sorted(set(formats)),
                round_evidence='REQUIRES_RUNTIME_TRACE', issues=issues, next_steps=steps)


def local_capture_gaps(directory, reported_steps, read):
    """Replay observed ledger inputs, then bind them to actual dispatcher pairs."""
    from .ngm_execution import NGMRoundLedger
    try:
        trace = read(directory/'wire-events.json')
        summary = read(directory/'summary.json')
        if (trace.get('schema') != 'tester-spin/ngm-ledger/v1' or
                trace.get('execution_scope') != 'official-local-demo' or
                trace.get('server_execution') is not False or not isinstance(trace.get('events'), list)):
            return ['NGM_LOCAL_TRACE_INVALID']
        ledger = NGMRoundLedger(trace.get('balance_before'))
        inputs, outputs = [], []
        for event in trace['events']:
            kind, value = event['kind'], event['value']
            if kind not in ('message','spin','response','payout') or (kind != 'response' and not isinstance(value, dict)):
                return ['NGM_LOCAL_TRACE_INVALID']
            ledger.accept(kind, value)
            if kind == 'spin':inputs.append(value)
            if kind == 'response':outputs.append(value)
        if not ledger.verified or ledger.spins != reported_steps:
            return ['NGM_LOCAL_TRACE_INCOMPLETE: '+', '.join(ledger.issues or ['STEP_COUNT_MISMATCH'])]
        if any(summary.get(key) != value for key, value in ledger.summary().items()):
            return ['NGM_LOCAL_SUMMARY_MISMATCH']
        previous = -1
        for index, (request, response) in enumerate(zip(inputs, outputs)):
            for direction, value in (('request', request), ('response', response)):
                pair = read(directory/f'step-{index}-{direction}.json')
                event_index = pair.get('event_index')
                if (pair.get('execution_scope') != 'official-local-demo' or pair.get('server_execution') is not False or
                        pair.get('source_sha256') != summary.get('source_sha256') or
                        type(event_index) is not int or event_index <= previous):
                    return ['NGM_LOCAL_PAIR_PROVENANCE_MISMATCH']
                previous = event_index
                observation = pair['observation']
                if observation['type'] != 'offline.'+direction:
                    return ['NGM_LOCAL_PAIR_TYPE_MISMATCH']
                captured = observation['data']['value']
                if direction == 'request':captured = captured['spin']
                if captured != value:
                    return ['NGM_LOCAL_PAIR_TRACE_MISMATCH']
        return []
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return ['NGM_LOCAL_EVIDENCE_MISSING_OR_INVALID']
