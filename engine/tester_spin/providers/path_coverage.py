from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from tester_spin.models import GameTestResult


_ACTIONABLE_KINDS = {
    "SPIN",
    "FEATURE_SPIN",
    "PURCHASE",
    "PURCHASE_BRANCH",
    "FEATURE",
    "CONTINUATION",
    "VARIANT",
    "CHOICE_BRANCH",
    "CHOICE_CONTINUATION",
    "INDEXED_CHOICE",
    "UNRESOLVED_STATE",
}


def _clean_option(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _option_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    found: list[str] = []
    for item in value:
        clean = _clean_option(item)
        if clean and clean not in found:
            found.append(clean)
    return found


def _mode_scope(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return ""
    if len(relative.parts) < 2:
        return ""
    first = str(relative.parts[0])
    if first.casefold() in {"bootstrap", "discovery", "catalog", "diagnostics"}:
        return ""
    return first


def _walk_pending_choices(value: Any, *, path: str = "$"):
    if isinstance(value, dict):
        choices = value.get("choices")
        if isinstance(choices, dict):
            selected = choices.get("selected")
            available = _option_list(choices.get("available"))
            if (selected is None or selected == "") and available:
                yield path + ".choices", available

        selected = value.get("selected")
        available = _option_list(value.get("availableChoices"))
        if (selected is None or selected == "") and available:
            yield path, available

        for key, child in value.items():
            yield from _walk_pending_choices(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_pending_choices(child, path=f"{path}[{index}]")


def _walk_selected_choices(value: Any):
    if isinstance(value, dict):
        if "choice" in value:
            clean = _clean_option(value.get("choice"))
            if clean:
                yield clean
        if str(value.get("action") or "").casefold() == "dofsoption":
            clean = _clean_option(value.get("ind"))
            if clean:
                yield clean
        for child in value.values():
            yield from _walk_selected_choices(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_selected_choices(child)


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _implicit_uncovered_action(mode: dict[str, Any]) -> dict[str, Any] | None:
    """Turn an advertised-but-unexecuted provider action into required coverage.

    Providers use slightly different metadata vocabularies. The shared invariant is
    intentionally conservative: only gameplay-like kinds participate. Pure
    DISCOVERED_ONLY/telemetry rows remain diagnostics. If an actionable row says
    ``executable=False`` or ``observed=False``, it cannot silently coexist with OK,
    unless the provider explicitly marks it diagnostic-only with
    ``coverage_required=False``.
    """
    kind = str(mode.get("kind") or "").upper()
    if kind not in _ACTIONABLE_KINDS:
        return None
    if mode.get("coverage_required") is False:
        return None
    # HyperHive carries this state through its neutral discovered-mode mapping;
    # it means the string exists in client code but no live req serializer/menu
    # evidence proved that the action is actually available to this game.
    if str(mode.get("discovery_state") or "").upper() == "DISCOVERED_LITERAL_ONLY":
        return None
    if mode.get("coverage_required") is True:
        return None
    explicitly_unexecutable = mode.get("executable") is False
    advertised_not_executed = mode.get("observed") is False
    if not (explicitly_unexecutable or advertised_not_executed):
        return None

    mode_id = str(mode.get("id") or "UNKNOWN")
    option = (
        _clean_option(mode.get("wire_command"))
        or _clean_option(mode.get("feature_buy"))
        or _clean_option(mode.get("identifier"))
        or mode_id
    )
    return {
        "source": "discovered_modes_fail_closed",
        "mode_id": mode_id,
        "signature": str(mode.get("branch_signature") or f"{mode_id}:UNEXECUTED"),
        "required": [option],
        "covered": [],
    }


def _explicit_branch_points(result: GameTestResult) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for mode in result.discovered_modes:
        if not isinstance(mode, dict):
            continue
        mode_id = str(mode.get("id") or "UNKNOWN")

        if mode.get("coverage_required") is True:
            required = _option_list(
                mode.get("required_options")
                if mode.get("required_options") is not None
                else mode.get("available")
            )
            covered = _option_list(
                mode.get("covered_options")
                if mode.get("covered_options") is not None
                else mode.get("selected_options")
            )
            if not required:
                required = ["DOMAIN_UNRESOLVED"]
                covered = []
            if not covered:
                one = _clean_option(mode.get("selected_for_validation"))
                if one:
                    covered = [one]
            if required:
                points.append(
                    {
                        "source": "discovered_modes",
                        "mode_id": mode_id,
                        "signature": str(mode.get("branch_signature") or mode_id),
                        "required": required,
                        "covered": covered,
                        "required_samples": mode.get("required_samples", 1),
                        "sample_counts": mode.get("sample_counts"),
                    }
                )
        else:
            implicit = _implicit_uncovered_action(mode)
            if implicit is not None:
                points.append(implicit)

        for index, domain in enumerate(mode.get("choice_domains") or []):
            if not isinstance(domain, dict) or not domain.get("options"):
                continue
            # Choices remain separate from the commercial option that opened
            # them; a completed purchase is not proof of every nested branch.
            scalar = lambda values: _option_list([
                str(value).lower() if isinstance(value, bool) else value
                for value in values
            ])
            points.append({
                "source": "declared_choice_domain",
                "mode_id": mode_id,
                "signature": f"{mode_id}:choice:{index}:{domain.get('state', '')}:{domain.get('request_field', 'selectedIndex')}",
                "required": scalar(domain["options"]),
                "covered": scalar(domain.get("covered") or []),
            })

            from .repeat_purchase import POLICY, repeat_complete
            if domain.get("repeat_purchase_policy") == POLICY:
                points.append({
                    "source": "repeat_purchase_probe",
                    "mode_id": mode_id,
                    "signature": f"{mode_id}:repeat-purchase:{index}:{domain.get('state', '')}",
                    "required": ["closed_purchase_chain"],
                    "covered": ["closed_purchase_chain"] if repeat_complete(domain) else [],
                })

        fs_required = _option_list(mode.get("fs_option_indices"))
        if fs_required:
            points.append(
                {
                    "source": "pragmatic_fso",
                    "mode_id": mode_id,
                    "signature": f"{mode_id}:doFSOption",
                    "required": fs_required,
                    "covered": _option_list(mode.get("fs_option_selected")),
                }
            )
    return points


def _artifact_branch_points(result: GameTestResult) -> list[dict[str, Any]]:
    if not result.run_dir:
        return []
    root = Path(str(result.run_dir or ""))
    if not root.is_dir():
        return []

    pending: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    pragmatic_fso: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    prefixes: dict[Path, list[str]] = {}
    validated = {
        Path(a.artifact_dir).resolve()
        for a in result.attempts
        if a.artifact_dir and a.ok and a.terminal and not a.warning and not a.error
    }

    for path in sorted(root.rglob("*.json")):
        if path.name in {"result.json", "path-coverage.json", "sample-catalog.json"}:
            continue
        mode_id = _mode_scope(root, path)
        if not mode_id:
            continue
        payload = _load_json(path)
        if payload is None:
            continue

        if (
            isinstance(payload, dict)
            and payload.get("schema") == "tester-spin/pragmatic-fso-selection/v1"
        ):
            required = _option_list(payload.get("option_indices"))
            selected = _clean_option(payload.get("selected_index"))
            if required:
                # Wire-step numbers vary with random cascades. Identify a prompt
                # by earlier selections, so sibling subtrees never share credit.
                prefix = prefixes.setdefault(path.parent, [])
                head = "/".join(prefix) if prefix else "ROOT"
                signature = f"{mode_id}:FSO:{head}"
                key = (mode_id, signature, tuple(sorted(required)))
                item = pragmatic_fso.setdefault(
                    key,
                    {
                        "source": "pragmatic_fso_artifact",
                        "mode_id": mode_id,
                        "signature": signature,
                        "required": required,
                        "covered": set(),
                    },
                )
                if selected and path.parent.resolve() in validated:
                    item["covered"].add(selected)
                prefix.append(selected or "<unresolved>")
            continue

        lowered = path.name.casefold()
        if "request" in lowered:
            continue
        if "response" not in lowered and "summary" not in lowered and "attempt" not in lowered:
            continue

        from .yggdrasil.choice_coverage import resolved_menu
        for json_path, required in _walk_pending_choices(payload):
            if json_path == "$.choices" and resolved_menu(result, mode_id, path, payload, validated):
                continue
            # Red Tiger supplies a typed, prefix-sensitive graph from its executor.
            # Do not replace that graph with a mode-wide bag of request values.
            if result.provider == "redtiger" and any(
                m.get("kind") == "CHOICE_BRANCH" and m.get("parent") == mode_id
                for m in result.discovered_modes if isinstance(m, dict)
            ):
                continue
            key = (mode_id, json_path, tuple(sorted(required)))
            pending.setdefault(
                key,
                {
                    "source": "artifact_scan",
                    "mode_id": mode_id,
                    "signature": f"{mode_id}:{json_path}",
                    "required": required,
                },
            )

    points: list[dict[str, Any]] = []
    for item in pending.values():
        required = list(item["required"])
        points.append({**item, "covered": []})
    for item in pragmatic_fso.values():
        points.append(
            {
                **item,
                "covered": sorted(item["covered"]),
            }
        )
    return points


def _declared_feature_points(result: GameTestResult) -> list[dict[str, Any]]:
    points = []
    verified_ids = set()
    if result.provider == 'pragmatic':
        from tester_spin.providers.pragmatic_declared_coverage import verified_mode_ids
        verified_ids = verified_mode_ids(result)
    for category, domain in result.feature_domains.items():
        if not isinstance(domain, dict) or not domain.get('source'):
            continue
        if domain.get('complete') is False:
            required, covered = ['DOMAIN_UNRESOLVED'], []
        elif domain.get('complete') is True and isinstance(domain.get('options'), list):
            required = _option_list(domain['options'])
            covered_set = set()
            for mode in result.discovered_modes:
                kind = str(mode.get('kind') or '').upper()
                request = mode.get('request') or {}
                purchase = mode.get('purchase') or {}
                name = str(mode.get('purchased_feature') or mode.get('purchase_name') or request.get('purchased_feature') or purchase.get('name') or '')
                vip = mode.get('id') == 'BELATRA_START_SELECTOR_MATRIX'
                ante = kind.startswith('ANTE_BET') or vip or 'CHANCE' in name.upper().split('_')
                if category == 'feature_spin' and kind != 'FEATURE_SPIN':
                    continue
                if category == 'ante' and not ante or category == 'purchase' and (ante or kind not in {'PURCHASE', 'PURCHASE_BRANCH'}):
                    continue
                if result.provider == 'pragmatic':
                    if mode.get('id') in verified_ids:
                        covered_set.add(str(mode['id']))
                    continue
                covered_set.update(_option_list(mode.get('covered_options')))
                if mode.get('validated') is True:
                    covered_set.add(str(mode.get('id') or ''))
                    for field in ('selected_mode', 'buyBonus', 'feature_buy'):
                        if mode.get(field) is not None:
                            covered_set.add(str(mode[field]))
                    level = mode.get('purchased_feature_level', mode.get('purchase_level', mode.get('feature_level', request.get('purchased_feature_level', purchase.get('level')))))
                    if name:
                        covered_set.add(name + (':'+str(level) if level is not None else ''))
                    options = _option_list(mode.get('required_options'))
                    if len(options) == 1:
                        covered_set.update(options)
                if vip and any('vipOn=1' in option.split('|') for option in _option_list(mode.get('covered_options'))):
                    covered_set.add('vipOn=1')
            covered = [option for option in required if option in covered_set]
        else:
            continue
        if required:
            points.append({'source': domain['source'], 'mode_id': category.upper()+'_DECLARATION',
                           'signature': category+':DECLARED_DOMAIN', 'required': required, 'covered': covered})
    return points


def _paid_inventory_points(result: GameTestResult) -> list[dict[str, Any]]:
    """Known paths are insufficient: every provider must prove enumeration.

    Adapters must persist a fresh inventory independently of execution coverage.
    Missing inventory (including an unproven zero) fails closed. This gate never
    derives paid-option counts from successful spins or from mode names.
    """
    from tester_spin.paid_options import SCHEMA
    inventory = result.structural_map.get('paid_option_inventory') or {}
    options = inventory.get('options')
    valid = (inventory.get('complete') is True and bool(inventory.get('source'))
             and isinstance(options, list) and inventory.get('schema') == SCHEMA
             and inventory.get('provider') == result.provider
             and inventory.get('game') == result.slug
             and inventory.get('symbol') == result.symbol
             and isinstance(inventory.get('primitive'), dict)
             and bool(inventory['primitive'].get('id'))
             and bool(inventory['primitive'].get('version')))
    ids = []
    if isinstance(options, list):
        for option in options:
            if (not isinstance(option, dict) or not option.get('id')
                    or option.get('category') in {None, '', 'unknown'}):
                valid = False
                continue
            ids.append(str(option['id']))
        valid = valid and len(set(ids)) == len(ids)
        categories = Counter(option.get('category') for option in options if isinstance(option,dict))
        valid = (valid and type(inventory.get('count')) is int
                 and inventory['count'] == len(options)
                 and inventory.get('counts_by_category') == dict(categories))
    evidence_ok = False
    root = Path(result.run_dir).resolve() if result.run_dir else None
    for filename in inventory.get('evidence_files', []):
        if root is None:
            break
        try:
            path = (root / filename).resolve()
            path.relative_to(root)
            evidence = json.loads(path.read_text(encoding='utf-8'))
            keys = ('schema','provider','game','symbol','primitive','source','complete','options','evidence','count','counts_by_category')
            proofs = evidence.get('evidence')
            proofs_ok = isinstance(proofs, list) and bool(proofs)
            for proof in proofs if isinstance(proofs, list) else []:
                proof_path = (root / proof['path']).resolve()
                proof_path.relative_to(root)
                if hashlib.sha256(proof_path.read_bytes()).hexdigest() != proof['sha256']:
                    proofs_ok = False
            if (proofs_ok and evidence.get('complete') is True
                    and all(evidence.get(key) == inventory.get(key) for key in keys)):
                evidence_ok = True
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            continue
    covered = {str(attempt.mode_id) for attempt in result.attempts
               if attempt.ok and attempt.terminal and not attempt.error and not attempt.warning}
    covered_options = set()
    for option in options if isinstance(options,list) else []:
        if not isinstance(option,dict):continue
        execution_ids=option.get('execution_ids',[str(option.get('id',''))])
        if (isinstance(execution_ids,list) and execution_ids
                and all(str(identity) in covered for identity in execution_ids)):
            covered_options.add(str(option.get('id','')))
    return [
        {'source': 'paid_option_inventory', 'mode_id': 'PAID_INVENTORY',
         'signature': 'paid:enumeration', 'required': ['VERIFIED_COMPLETE_INVENTORY'],
         'covered': ['VERIFIED_COMPLETE_INVENTORY'] if valid and evidence_ok else []},
        {'source': 'paid_option_inventory', 'mode_id': 'PAID_OPTIONS',
         'signature': 'paid:execution', 'required': ids,
         'covered': sorted(covered_options.intersection(ids))},
    ]


def build_path_coverage_report(result: GameTestResult) -> dict[str, Any]:
    points = _explicit_branch_points(result)
    points.extend(_paid_inventory_points(result))
    points.extend(_declared_feature_points(result))
    explicit_signatures = {str(item["signature"]): item for item in points}
    for item in _artifact_branch_points(result):
        existing = explicit_signatures.get(str(item["signature"]))
        if existing is None:
            points.append(item)
        else:
            # Persisted evidence may reveal options omitted by adapter metadata.
            existing["required"] = list(dict.fromkeys(existing["required"] + item["required"]))
            existing["covered"] = [v for v in existing["covered"] if v in item["covered"]]

    normalized: list[dict[str, Any]] = []
    for item in points:
        required = list(dict.fromkeys(_option_list(item.get("required"))))
        covered = list(dict.fromkeys(_option_list(item.get("covered"))))
        missing = [value for value in required if value not in covered]
        target = max(1, int(item.get("required_samples") or 1))
        counts = item.get("sample_counts")
        deficits = {
            option: max(0, target - int(counts.get(option, 0)))
            for option in required
        } if isinstance(counts, dict) else {}
        missing = list(dict.fromkeys(missing + [k for k, v in deficits.items() if v]))
        normalized.append(
            {
                "source": str(item.get("source") or "unknown"),
                "mode_id": str(item.get("mode_id") or "UNKNOWN"),
                "signature": str(item.get("signature") or ""),
                "required": required,
                "covered": covered,
                "missing": missing,
                "complete": not missing,
                "required_samples": target,
                "sample_counts": counts,
                "sample_deficits": deficits,
            }
        )

    return {
        "schema": "tester-spin/path-coverage/v1",
        "provider": result.provider,
        "game": result.slug,
        "branch_points": normalized,
        "complete": all(item["complete"] for item in normalized),
        "missing_count": sum(len(item["missing"]) for item in normalized),
    }


def _append_error(result: GameTestResult, text: str) -> None:
    clean = str(text or "").strip()
    if not clean or clean in str(result.error or ""):
        return
    result.error = (str(result.error or "").strip() + " " + clean).strip()


def enforce_complete_path_coverage(
    result: GameTestResult,
    *,
    progress=None,
) -> GameTestResult:
    """Global invariant: an observed selectable branch cannot be silently skipped.

    This layer never invents provider requests. Provider adapters remain responsible
    for executing branches whose wire contract they understand. The neutral gate
    only verifies evidence and prevents OK when a discovered option is uncovered.
    """
    report = build_path_coverage_report(result)
    missing = [item for item in report["branch_points"] if item["missing"]]

    if result.run_dir:
        root = Path(result.run_dir)
        try:
            root.mkdir(parents=True, exist_ok=True)
            (root / "path-coverage.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    if missing:
        preview = "; ".join(
            f"{item['mode_id']} -> {item['missing']}" for item in missing[:8]
        )
        message = f"Cobertura de ramificaciones pendiente: {preview}."
        if result.status == "OK":
            result.status = "PARCIAL"
        if result.status not in {"ERROR", "CANCELADO"}:
            _append_error(result, message)
        if progress is not None:
            progress(message)
    elif report["branch_points"] and progress is not None:
        total = sum(len(item["required"]) for item in report["branch_points"])
        progress(f"Cobertura de ramificaciones completa: {total}/{total} opciones recorridas.")

    if result.run_dir:
        try:
            (Path(result.run_dir) / "result.json").write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
    return result
