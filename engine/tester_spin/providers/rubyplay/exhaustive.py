from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from tester_spin.models import Game, GameTestResult
from tester_spin.providers.base import Progress
from tester_spin.providers.rubyplay.adapter import RubyPlayProvider as _RubyPlayProvider


INDEX_BRANCH_ACTIONS = {"select", "pick"}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _observed_index_actions(result: GameTestResult, *, accepted_only: bool = False, terminal_only: bool = False) -> dict[str, set[int]]:
    found: dict[str, set[int]] = {}
    root = Path(str(result.run_dir or ""))
    if not root.is_dir():
        return found
    for path in root.rglob("*request.json"):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        action = str(payload.get("action") or "").strip().lower()
        if action not in INDEX_BRANCH_ACTIONS:
            continue
        if accepted_only:
            response = _load_json(path.with_name(path.name.replace("request.json", "response.json")))
            if not response or response.get("status") != "ok":
                continue
            body = response.get("data")
            if not isinstance(body, dict) or not body.get("next_action"):
                continue
        if terminal_only:
            audit = _load_json(path.parent / "return-to-base.json") or {}
            if audit.get("status") != "CONFIRMED" or audit.get("required", 0) < 2 or audit.get("consecutive_base", 0) < 2:
                continue
            responses = list(path.parent.glob("step-*-response.json"))
            responses.sort(key=lambda item: int(re.search(r"step-(\d+)", item.name).group(1)))
            final = _load_json(responses[-1]) if responses else None
            if not final or final.get("status") != "ok" or final.get("data", {}).get("next_action") != "spin":
                continue
        index = payload.get("index")
        if isinstance(index, bool):
            continue
        try:
            parsed = int(index)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            found.setdefault(action, set()).add(parsed)
    return found


def apply_rubyplay_path_audit(
    result: GameTestResult,
    *,
    progress: Progress,
) -> GameTestResult:
    """Require a certified domain and terminal, return-to-base option evidence.

    Unknown client shapes stay unresolved. A certified generated client contract
    supplies finite indices; requests alone never count as covered choices.
    """
    if result.status in {"ERROR", "CANCELADO"} or not result.run_dir:
        return result

    observed = _observed_index_actions(result)
    if not observed:
        return result

    accepted = _observed_index_actions(result, accepted_only=True)
    try:
        evidence = json.loads(Path(result.run_dir, "bootstrap", "index-domain-evidence.json").read_text(encoding="utf-8"))
        if not isinstance(evidence, list):
            evidence = []
    except (OSError, ValueError):
        evidence = []

    terminal = _observed_index_actions(result, accepted_only=True, terminal_only=True)
    pending: list[str] = []
    for action, indexes in sorted(observed.items()):
        action_evidence = [item for item in evidence if isinstance(item, dict) and item.get("action") == action]
        domains = {tuple(item.get("candidate_indices", [])) for item in action_evidence if item.get("domain_proven") is True and item.get("proof_excerpts")}
        domain = next(iter(domains)) if len(domains) == 1 else ()
        required = [str(value) for value in domain] if domain else ["DOMAIN_UNRESOLVED"]
        covered = [str(value) for value in domain if value in terminal.get(action, set())]
        if set(required) - set(covered):
            pending.append(f"{action}: {sorted(set(required) - set(covered))}")
        result.discovered_modes.append(
            {
                "id": f"RUBYPLAY_{action.upper()}_INDEX_DOMAIN",
                "kind": "INDEXED_CHOICE",
                "observed": True,
                "executable": True,
                "wire_command": action,
                "observed_indices": sorted(indexes),
                "accepted_indices": sorted(accepted.get(action, set())),
                "domain_evidence": action_evidence,
                "coverage_required": True,
                "branch_signature": f"RUBYPLAY:{action}:index-domain",
                "required_options": required,
                "covered_options": covered,
                "reason": ("dominio finito certificado; cobertura requiere cadena terminal y dos normales consecutivas" if domain else
                    "el cliente demuestra que la acción usa index, pero los HAR/"
                    "contratos actuales no demuestran el dominio completo; no se "
                    "puede considerar exhaustiva una elección arbitraria"
                ),
            }
        )

    if pending and result.status == "OK":
        result.status = "PARCIAL"
    if pending:
        message = "RubyPlay cobertura indexada pendiente: " + "; ".join(pending)
        if message not in str(result.error or ""):
            result.error = (str(result.error or "").strip() + " " + message).strip()
        progress(message)
    else:
        progress("RubyPlay cobertura indexada certificada: " + ", ".join(sorted(observed)))

    try:
        Path(result.run_dir, "result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return result


class RubyPlayProvider(_RubyPlayProvider):
    """RubyPlay adapter with fail-closed exhaustive branch semantics."""

    def test_game(
        self,
        game: Game,
        *,
        spins: int,
        timeout_s: float,
        stop_event: threading.Event,
        progress: Progress,
    ) -> GameTestResult:
        result = super().test_game(
            game,
            spins=spins,
            timeout_s=timeout_s,
            stop_event=stop_event,
            progress=progress,
        )
        return apply_rubyplay_path_audit(result, progress=progress)


__all__ = ["RubyPlayProvider", "apply_rubyplay_path_audit"]
