from __future__ import annotations

import re
import sys
import threading
import weakref
from typing import Any


_install_lock = threading.Lock()
_installed = False
_evidence_by_session: weakref.WeakKeyDictionary[Any, dict[str, Any]] = weakref.WeakKeyDictionary()


def _params_req_aliases(text: str) -> set[str]:
    return set(
        re.findall(
            r'\bparams\s*:\s*\{[^{}]{0,2000}\breq\s*:\s*([A-Za-z_$][A-Za-z0-9_$]*)(?=[,}])',
            text or "",
        )
    )


def _has_req_bet_type_evidence(text: str) -> bool:
    """Prove normal-spin bet_type only from the req object that is serialized.

    HyperHive clients can assign ``bet_type='freebet'`` only for freebet spins,
    while unrelated helpers elsewhere in the bundle may contain ``req.bet_type``.
    When ``params.req`` is an identifier, only that same alias is authoritative.
    A literal ``freebet`` assignment is deliberately not evidence that normal
    spins carry a bet_type field.
    """
    from tester_spin.providers.bgaming.forwarded_request import forwarded_request_contracts
    source = (text or "") + "\n" + forwarded_request_contracts(text)
    aliases = _params_req_aliases(source)
    if aliases:
        for alias in aliases:
            escaped = re.escape(alias)
            for object_match in re.finditer(
                rf'(?:\b(?:const|let|var)\s+)?\b{escaped}\s*=\s*\{{([^{{}}]{{0,2000}})\}}',
                source,
            ):
                body = object_match.group(1)
                for value in re.findall(
                    r'(?:^|,)\s*bet_type\s*:\s*["\']([^"\']+)["\']',
                    body,
                ):
                    if value.casefold() != "freebet":
                        return True

            assignment_patterns = (
                rf'\b{escaped}\.bet_type\s*=\s*["\']([^"\']+)["\']',
                rf'\b{escaped}\[["\']bet_type["\']\]\s*=\s*["\']([^"\']+)["\']',
            )
            for pattern in assignment_patterns:
                for value in re.findall(pattern, source):
                    if value.casefold() != "freebet":
                        return True
        return False

    # Clients that serialize req inline have no alias to trace. Preserve the
    # direct, req-scoped contract shapes used by those games.
    return bool(
        re.search(
            r'(?:\breq\s*:\s*\{[^{}]{0,1600}\bbet_type\s*:|\.req\.bet_type\s*=|\.req\[["\']bet_type["\']\]\s*=)',
            source,
        )
    )


def _wire_contract_evidence(text: str) -> dict[str, Any]:
    """Return source-free syntax evidence for HyperHive request discovery.

    The report intentionally contains only booleans/counts and symbolic pattern
    names. It never returns client source, string literal contents, URLs, tokens,
    or session material, so it can be embedded in sanitized Actions diagnostics.
    """
    compact = re.sub(r"\s+", "", text or "")
    patterns = {
        "method_play": r'(?:\bmethod|["\']method["\'])\s*:\s*["\']play["\']',
        "params_req_object": r'\bparams\s*:\s*\{[^{}]{0,2000}\breq\s*:',
        "params_req_property": r'\.params\.req\b',
        "req_bet_object_value": r'\breq\s*:\s*\{[^{}]{0,2000}\bbet\s*:',
        "req_bet_dot_assignment": r'\.req\.bet\s*=',
        "req_bet_bracket_assignment": r'\.req\[["\']bet["\']\]\s*=',
        "req_bet_shorthand": (
            r'\breq\s*:\s*\{(?:bet(?=[,}])|[^{}]{0,2000},bet(?=[,}]))'
        ),
        "req_bet_type_object": r'\breq\s*:\s*\{[^{}]{0,2000}\bbet_type\s*:',
        "req_bet_type_dot_assignment": r'\.req\.bet_type\s*=',
        "req_bet_type_bracket_assignment": r'\.req\[["\']bet_type["\']\]\s*=',
        "custom_req": r'\bcustom_req\b',
        "jsonrpc": r'\bjsonrpc\b',
    }
    evidence: dict[str, Any] = {
        name: bool(re.search(pattern, compact))
        for name, pattern in patterns.items()
    }

    aliases = _params_req_aliases(compact)
    evidence["params_req_identifier"] = bool(aliases)
    alias_bet = False
    alias_bet_type = False
    alias_object_bet_value = False
    alias_object_bet_shorthand = False
    for alias in aliases:
        escaped = re.escape(alias)
        if re.search(
            rf'(?:\b{escaped}\.bet\s*=|\b{escaped}\[["\']bet["\']\]\s*=)',
            compact,
        ):
            alias_bet = True
        if re.search(
            rf'(?:\b{escaped}\.bet_type\s*=|\b{escaped}\[["\']bet_type["\']\]\s*=)',
            compact,
        ):
            alias_bet_type = True
        for object_match in re.finditer(
            rf'(?:const|let|var)?{escaped}\s*=\s*\{{([^{{}}]{{0,2000}})\}}',
            compact,
        ):
            body = object_match.group(1)
            if re.search(r'(?:^|,)bet:', body):
                alias_object_bet_value = True
            if re.search(r'(?:^|,)bet(?=,|$)', body):
                alias_object_bet_shorthand = True
    evidence["req_alias_bet_dot_assignment"] = alias_bet
    evidence["req_alias_bet_type_dot_assignment"] = alias_bet_type
    evidence["req_alias_object_bet_value"] = alias_object_bet_value
    evidence["req_alias_object_bet_shorthand"] = alias_object_bet_shorthand
    evidence["normal_req_bet_type"] = _has_req_bet_type_evidence(compact)

    evidence["bet_token_count"] = min(9999, len(re.findall(r"\bbet\b", compact)))
    evidence["req_token_count"] = min(9999, len(re.findall(r"\breq\b", compact)))
    evidence["bet_type_token_count"] = min(9999, len(re.findall(r"\bbet_type\b", compact)))
    evidence["syntax_signatures"] = sorted(
        name for name, matched in evidence.items()
        if isinstance(matched, bool) and matched
    )
    return evidence


def _mode_diagnostic_metadata(mode: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "id": str(mode.get("id") or ""),
        "kind": str(mode.get("kind") or ""),
        "observed": bool(mode.get("observed", False)),
        "validated": bool(mode.get("validated", False)),
        "executable": bool(mode.get("executable")),
        "discovery_state": str(mode.get("discovery_state") or "DISCOVERED"),
        "wire_method": str(mode.get("wire_method") or "play"),
        "request_options": dict(mode.get("request") or mode.get("request_options") or {}),
        "source": str(mode.get("source") or ""),
    }
    evidence = mode.get("contract_evidence")
    if isinstance(evidence, dict):
        metadata["contract_evidence"] = dict(evidence)
    if isinstance(mode.get("coverage_required"), bool):
        metadata["coverage_required"] = bool(mode["coverage_required"])
    return metadata


def _remember_evidence(runtime: Any, evidence: dict[str, Any]) -> None:
    try:
        _evidence_by_session[runtime.session] = dict(evidence)
    except (AttributeError, TypeError):
        pass


def _read_evidence(runtime: Any) -> dict[str, Any]:
    try:
        return dict(_evidence_by_session.get(runtime.session) or {})
    except (AttributeError, TypeError):
        return {}


def install_contract_probe() -> None:
    """Attach safe structural evidence and contextual req predicates."""
    global _installed
    with _install_lock:
        if _installed:
            return

        from tester_spin.providers.bgaming import hyperhive, hyperhive_wire

        original_discover_modes = hyperhive.discover_modes_from_bundle
        original_run_hyperhive_test = hyperhive.run_hyperhive_test

        def probed_discover_modes(
            runtime,
            *,
            timeout_s: float,
            bundle_text: str | None = None,
            engine_contract: str = "",
        ):
            modes = original_discover_modes(
                runtime,
                timeout_s=timeout_s,
                bundle_text=bundle_text,
                engine_contract=engine_contract,
            )
            resolved_bundle = bundle_text or ""
            try:
                refreshed = hyperhive._download_bundle(runtime, timeout_s)
                if refreshed:
                    resolved_bundle = refreshed
            except Exception:
                pass
            evidence = _wire_contract_evidence(
                resolved_bundle + "\n" + (engine_contract or "")
            )
            _remember_evidence(runtime, evidence)
            base = next(
                (
                    mode for mode in modes
                    if isinstance(mode, dict) and str(mode.get("id") or "") == "SPIN"
                ),
                None,
            )
            if isinstance(base, dict):
                base["contract_evidence"] = evidence
            return modes

        def probed_run_hyperhive_test(*args, **kwargs):
            runtime = kwargs.get("runtime")
            result = original_run_hyperhive_test(*args, **kwargs)
            evidence = _read_evidence(runtime) if runtime is not None else {}
            if evidence:
                for mode in result.discovered_modes:
                    if isinstance(mode, dict) and str(mode.get("id") or "") == "SPIN":
                        mode["contract_evidence"] = evidence
                        break
            return result

        hyperhive.discover_modes_from_bundle = probed_discover_modes
        hyperhive.run_hyperhive_test = probed_run_hyperhive_test
        hyperhive._mode_diagnostic_metadata = _mode_diagnostic_metadata
        hyperhive_wire._has_req_bet_type_evidence = _has_req_bet_type_evidence

        execution_module = sys.modules.get("tester_spin.providers.bgaming.execution")
        if execution_module is not None:
            setattr(execution_module, "run_hyperhive_test", probed_run_hyperhive_test)

        _installed = True


__all__ = [
    "_has_req_bet_type_evidence",
    "_wire_contract_evidence",
    "_mode_diagnostic_metadata",
    "install_contract_probe",
]
