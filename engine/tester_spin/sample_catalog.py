"""Offline, evidence-linked inventory. Observed wire tags are not inferred semantics."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tester_spin.models import GameTestResult

_TAGS = {"command", "action", "na", "state", "phaseCur", "phaseNext", "spinMode", "st"}


def _ordered(path: Path) -> tuple:
    text = path.as_posix()
    entry = path.name in {"request.json", "response.json", "entry-request.json", "entry-response.json"}
    return (0 if entry else 1, tuple((0, int(x)) if x.isdigit() else (1, x) for x in re.split(r"(\d+)", text)))


def _tags(value: Any, prefix: str = "$") -> list[dict[str, Any]]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            location = prefix + "." + key
            if key in _TAGS and isinstance(child, (str, int, bool)):
                found.append({"field": location, "value": child})
            elif isinstance(child, (dict, list)):
                found.extend(_tags(child, location))
    elif isinstance(value, list):
        for child in value:
            found.extend(_tags(child, prefix + "[]"))
    return found


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _bgaming_choice(data: dict[str, Any]) -> dict[str, Any] | None:
    command = str(data.get("command", data.get("action")) or "")
    if not command:
        return None
    try:
        from tester_spin.providers.bgaming.contracts import command_contract
    except ImportError:
        return None
    contract = command_contract(command)
    choice = contract.choice if contract is not None else None
    if choice is None:
        return None
    options = data.get("options")
    if not isinstance(options, dict) or choice.option_field not in options:
        return None
    return {
        "command": command,
        "field": choice.option_field,
        "value": options[choice.option_field],
    }


def _choices(provider: str, root: Path, files: list[Path]) -> list[dict[str, Any]]:
    choices = []
    if provider == "pragmatic":
        for path in sorted(root.glob("fso-selection-*.json"), key=_ordered):
            data = _read(path)
            if isinstance(data, dict) and data.get("selected_index") is not None:
                choices.append({"command": "doFSOption", "value": data["selected_index"]})
    elif provider == "redtiger":
        summary = _read(root / "summary.json")
        if isinstance(summary, dict):
            if isinstance(summary.get('choice_continuations'), list):
                choices = [{"command":"choice","value":row['selected']}
                    for row in summary['choice_continuations']
                    if isinstance(row,dict) and row.get('selected') is not None]
            elif isinstance(summary.get("branch_prefix"), list):
                choices = [{"command": "choice", "value": value} for value in summary["branch_prefix"]]
            else:
                choices = [
                    {"command": "choice", "value": row["selected"]}
                    for row in summary.get("choice_continuations", [])
                    if isinstance(row, dict) and row.get("selected") is not None
                ]
    elif provider in {"bgaming", "rubyplay", "hacksaw"}:
        for path in files:
            if "request" not in path.name or path.suffix != ".json":
                continue
            data = _read(path)
            if not isinstance(data, dict):
                continue
            if provider == "hacksaw":
                instruction = data.get("continueInstructions")
                action = instruction.get("action") if isinstance(instruction, dict) else None
                if (isinstance(action, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", action)
                        and action != "win_presentation_complete"):
                    choices.append({"command": "bet", "field": "continueInstructions.action", "value": action})
                continue
            if provider == "bgaming":
                choice = _bgaming_choice(data)
                if choice is not None:
                    choices.append(choice)
                continue
            command = data.get("command", data.get("action"))
            if command in {"pick", "select"} and "index" in data:
                choices.append({"command": command, "field": "index", "value": data["index"]})
    return choices


def _sampling_routes(result, attempt, directory, root, route):
    if result.provider != 'redtiger':
        return [route]
    parent = directory.relative_to(root).parts[0]
    marker = next((m for m in result.discovered_modes if isinstance(m,dict)
        and m.get('kind')=='DIAGNOSTIC' and m.get('parent')==parent
        and m.get('observed') is True and m.get('coverage_required') is False
        and m.get('source')=='choice_transition.gameData.progress.level'
        and m.get('coverage_scope')=='available_actions_not_all_repeat_counts'
        and m.get('entry_prefix')==[]), None)
    if marker is None:
        return [route]
    options, repeats = marker.get('options'), marker.get('repeat_actions')
    proof = _read(directory/'return-to-base.json') or {}
    if (not isinstance(options,list) or not options or not isinstance(repeats,list)
            or not repeats or not all(isinstance(v,str) and v for v in options+repeats)
            or not set(repeats)<=set(options)
            or proof.get('status')!='CONFIRMED'
            or type(proof.get('consecutive_base')) is not int or proof['consecutive_base']<2):
        return [route]
    summary = _read(directory/'summary.json') or {}
    records = summary.get('choice_continuations')
    if not isinstance(records,list):
        return [route]
    if any(not isinstance(r,dict) or set(r.get('available',[]))!=set(options)
           or r.get('selected') not in options for r in records):
        return [route]
    kind = next((m.get('kind') for m in result.discovered_modes
                 if isinstance(m,dict) and m.get('id')==parent),None)
    if kind not in {'SPIN','PURCHASE','ANTE_BET'}:
        return [route]
    common = {'mode_id':parent,'mode_kind':kind,
              'coverage_basis':'server-confirmed-recurring-controls/v1'}
    routes = [{**common,'choices':[]}]
    for action in sorted({r['selected'] for r in records}):
        routes.append({**common,'choices':[{'command':'choice','value':action}]})
    return routes


def _include_evidence_file(provider: str, directory: Path, path: Path) -> bool:
    if "bootstrap" in path.relative_to(directory).parts:
        return False
    if "request" in path.name or "response" in path.name or path.name.startswith("http-") or path.name == "ws-attempt.json":
        return True
    if provider == "pragmatic" and path.name.startswith("fso-selection-") and path.suffix == ".json":
        return True
    if provider == "redtiger" and path.name == "summary.json":
        return True
    return False


def build_sample_catalog(result: GameTestResult, *, samples_per_path: int = 1) -> dict[str, Any]:
    target = max(1, int(samples_per_path))
    root = Path(result.run_dir).resolve() if result.run_dir else None
    groups: dict[str, dict[str, Any]] = {}
    state_types: dict[str, dict[str, Any]] = {}
    diagnostics = []
    seen: set[Path] = set()
    for attempt in result.attempts:
        directory = Path(attempt.artifact_dir).resolve() if attempt.artifact_dir else None
        if root is None or directory is None or not directory.is_relative_to(root) or not directory.is_dir():
            diagnostics.append({"attempt": attempt.number, "reason": "missing_or_external_artifacts"})
            continue
        if directory in seen:
            diagnostics.append({"attempt": attempt.number, "reason": "duplicate_artifact_directory"})
            continue
        seen.add(directory)
        files = sorted(
            (
                path
                for path in directory.rglob("*")
                if path.is_file()
                and path.resolve().is_relative_to(root)
                and _include_evidence_file(result.provider, directory, path)
            ),
            key=_ordered,
        )
        evidence = []
        states = []
        for path in files:
            try:
                raw = path.read_bytes()
            except OSError:
                diagnostics.append({"attempt": attempt.number, "reason": "unreadable_artifact", "path": path.relative_to(root).as_posix()})
                continue
            evidence.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            if path.suffix == ".json" and ("response" in path.name or path.name == "ws-attempt.json"):
                tags = _tags(_read(path))
                if tags and (not states or tags != states[-1]):
                    states.append(tags)
                if tags:
                    signature = hashlib.sha256(json.dumps(tags, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    state = state_types.setdefault(signature, {"id": signature, "observed_tags": tags, "evidence": []})
                    state["evidence"].append({"attempt": attempt.number, "mode_id": attempt.mode_id, "path": path.relative_to(root).as_posix()})
        route = {
            "mode_id": attempt.mode_id,
            "mode_kind": attempt.mode_kind,
            "choices": _choices(result.provider, directory, files),
        }
        valid = bool(attempt.ok and attempt.terminal and not attempt.warning and not attempt.error and evidence)
        for sampling_route in _sampling_routes(result,attempt,directory,root,route):
            key = hashlib.sha256(json.dumps(sampling_route, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            group = groups.setdefault(key, {"id": key, **sampling_route, "validated_samples": 0, "samples": []})
            group["validated_samples"] += int(valid)
            group["samples"].append({
                "attempt": attempt.number,
                "artifact_dir": directory.relative_to(root).as_posix(),
                "validated": valid,
                "terminal": attempt.terminal,
                "observed_state_sequence": states,
                "evidence": evidence,
            })
    for group in groups.values():
        group["missing_samples"] = max(0, target - group["validated_samples"])
    return {
        "schema": "tester-spin/sample-catalog/v2",
        "provider": result.provider,
        "game": result.slug,
        "scope": ("observed_paths_and_recurring_controls" if any(
            g.get('coverage_basis')=='server-confirmed-recurring-controls/v1' for g in groups.values())
            else "observed_paths_only"),
        "samples_per_path": target,
        "groups": list(groups.values()),
        "observed_state_types": list(state_types.values()),
        "diagnostics": diagnostics,
        "observed_paths_sampled": bool(groups) and not diagnostics and all(group["missing_samples"] == 0 for group in groups.values()),
    }


def write_sample_catalog(result: GameTestResult, *, samples_per_path: int = 1) -> dict[str, Any]:
    report = build_sample_catalog(result, samples_per_path=samples_per_path)
    if result.run_dir:
        (Path(result.run_dir) / "sample-catalog.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
