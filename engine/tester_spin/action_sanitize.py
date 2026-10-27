from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tester_spin.providers.bgaming.runtime import sanitize_error_text, sanitize_session_url
from tester_spin.run_diagnostics import sanitize


_SAFE_DIAGNOSTIC_FILES = (
    "diagnostic.json",
    "diagnostic.md",
    "path-coverage.json",
    "path-catalog.json",
    "wager-catalog.json",
)


def sanitize_action_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_action_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_action_value(item) for item in value]
    if isinstance(value, str):
        cleaned = sanitize_error_text(value)
        if cleaned.startswith(("http://", "https://")):
            cleaned = sanitize_session_url(cleaned)
        return sanitize(cleaned)
    return value


def copy_safe_diagnostics(run_dir: Path, output_dir: Path) -> list[str]:
    """Export only sanitized structural reports, never raw wire captures/HAR."""
    copied: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in _SAFE_DIAGNOSTIC_FILES:
        source = run_dir / name
        if not source.is_file():
            continue
        target = output_dir / name
        if source.suffix == ".json":
            try:
                value = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            target.write_text(
                json.dumps(
                    sanitize_action_value(value),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        else:
            target.write_text(
                str(
                    sanitize_action_value(
                        source.read_text(encoding="utf-8", errors="replace")
                    )
                ),
                encoding="utf-8",
            )
        copied.append(name)
    return copied
