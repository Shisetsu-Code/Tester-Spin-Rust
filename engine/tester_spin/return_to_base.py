"""Bounded verification using a callback bound to the existing live session."""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from contextvars import ContextVar
from contextlib import contextmanager

_enabled = ContextVar('session_audit_enabled', default=False)
_blocked = ContextVar('session_audit_blocked', default=False)
_stop_event = ContextVar('session_audit_stop', default=None)

def audit_stop_event():
    return _stop_event.get()


def audit_enabled():
    return _enabled.get()


def audit_blocked():
    return _enabled.get() and _blocked.get()


@contextmanager
def audit_scope(stop_event=None):
    stop_token = _stop_event.set(stop_event)
    token = _enabled.set(True)
    blocked_token = _blocked.set(False)
    from tester_spin.server_observations import reset_live_observer
    reset_live_observer()
    try:
        yield
    finally:
        _stop_event.reset(stop_token)
        _enabled.reset(token)
        _blocked.reset(blocked_token)


def save_exchange(directory, request, response, step=1):
    from tester_spin.run_diagnostics import sanitize
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in [('request', request), ('response', response)]:
        (directory/f'step-{step:03d}-{name}.json').write_text(json.dumps(sanitize(value), ensure_ascii=False, indent=2), encoding='utf-8')
    return {'step': step, 'request': sanitize(request), 'response': sanitize(response)}


def pending_return(attempt_dir, reason):
    from tester_spin.run_diagnostics import sanitize
    attempt_dir.mkdir(parents=True, exist_ok=True)
    proof = {'schema': 'tester-spin/return-to-base/v1', 'status': 'REVIEW_REQUIRED',
             'connection_reused': True, 'required': 2, 'consecutive_base': 0, 'probes': [], 'reason': reason}
    (attempt_dir/'return-to-base.json').write_text(json.dumps(sanitize(proof), ensure_ascii=False, indent=2), encoding='utf-8')
    _blocked.set(True)
    return proof


def verify_return_to_base(attempt_dir: Path, play, *, stop_event=None, required=2, max_probes=10, observed_only=False):
    from tester_spin.run_diagnostics import sanitize
    if stop_event is None:
        stop_event = audit_stop_event()
    if required < 1 or max_probes < required:
        raise ValueError('Invalid return-to-base limits')
    attempt_dir.mkdir(parents=True, exist_ok=True)
    proof = {'schema': 'tester-spin/return-to-base/v1', 'status': 'RUNNING',
             'connection_reused': True, 'required': required, 'max_probes': max_probes,
             'consecutive_base': 0, 'cause': 'UNDETERMINED', 'probes': []}

    counter_key = 'consecutive_observed_state' if observed_only else 'consecutive_base'
    if observed_only:
        proof[counter_key] = 0
        proof['reason'] = 'Comparación empírica: significado terminal del estado no demostrado.'

    def persist():
        proof['updated_at'] = datetime.now(timezone.utc).isoformat()
        (attempt_dir/'return-to-base.json').write_text(json.dumps(sanitize(proof), ensure_ascii=False, indent=2), encoding='utf-8')

    persist()
    for index in range(1, max_probes+1):
        if stop_event is not None and stop_event.is_set():
            proof['status'] = 'CANCELLED'
            break
        directory = attempt_dir/'return-to-base'/f'probe-{index:03d}'
        directory.mkdir(parents=True, exist_ok=True)
        from tester_spin.server_observations import set_capture_directory
        previous_directory = set_capture_directory(directory)
        try:
            observed = play(directory)
            base_match = observed.get('base')
            if observed_only:
                observed['matches_observed_state'] = observed.pop('base', False)
                observed['base'] = False
            observed['directory'] = str(directory.relative_to(attempt_dir))
            proof['probes'].append(observed)
            if not observed.get('ok'):
                proof['status'] = 'ERROR'
            elif not observed.get('known'):
                proof['status'] = 'REVIEW_REQUIRED'
            else:
                proof[counter_key] = proof[counter_key]+1 if base_match else 0
                if proof[counter_key] >= required:
                    proof['status'] = 'OBSERVED_RETURN' if observed_only else 'CONFIRMED'
        except Exception as exc:
            proof['probes'].append({'directory': str(directory.relative_to(attempt_dir)), 'error': f'{type(exc).__name__}: {exc}'})
            proof['status'] = 'CANCELLED' if isinstance(exc, InterruptedError) or (stop_event is not None and stop_event.is_set()) else 'ERROR'
        finally:
            set_capture_directory(previous_directory)
        persist()
        if proof['status'] != 'RUNNING':
            break
    if proof['status'] == 'RUNNING':
        proof['status'] = 'LIMIT_REACHED'
    if proof['status'] not in {'CONFIRMED', 'OBSERVED_RETURN'}:
        _blocked.set(True)
    persist()
    return proof
