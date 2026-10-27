"""Read only the calibration trace explicitly linked to an attempt's protocol."""
from __future__ import annotations
import json
from pathlib import Path


def _read(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def linked_preparation(attempt, result):
    if not attempt.artifact_dir:
        return None
    directory = Path(attempt.artifact_dir)
    protocol = _read(directory / 'bootstrap' / 'protocol.json')
    link = protocol.get('preparation_dir')
    symbol = str(protocol.get('symbol') or '')
    expected = str(getattr(attempt, 'symbol', '') or getattr(result, 'symbol', '') or symbol)
    if not isinstance(link, str) or not link or not symbol or symbol != expected:
        return None
    target = Path(link)
    if not target.is_absolute():
        target = directory / target
    target = target.resolve()
    # The persisted format points to one bootstrap-runs/<trace> directory.
    # Never crawl all siblings or follow a nested preparation link.
    if target.parent.name != 'bootstrap-runs' or not target.is_dir():
        return None
    preparation_protocol = _read(target / 'bootstrap' / 'protocol.json')
    if str(preparation_protocol.get('symbol') or '') != symbol:
        return None
    return target


def selection_artifacts(attempt, result, pattern, *, recursive_attempt=False):
    """Yield origins: paid attempt, normal base probe, or linked bootstrap."""
    if not attempt.artifact_dir:
        return
    directory = Path(attempt.artifact_dir)
    paths = directory.rglob(pattern) if recursive_attempt else directory.glob(pattern)
    for path in sorted(paths):
        relative = path.relative_to(directory)
        base_probe = (len(relative.parts) >= 3 and relative.parts[0] == 'return-to-base'
                      and relative.parts[1].startswith('probe-'))
        yield path, 'SPIN' if base_probe else attempt.mode_id, 'base_probe' if base_probe else 'attempt'
    preparation = linked_preparation(attempt, result)
    if preparation is not None:
        for path in sorted(preparation.rglob(pattern)):
            yield path, 'SPIN', 'bootstrap'
