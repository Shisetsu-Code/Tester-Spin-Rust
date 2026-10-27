from __future__ import annotations

from tester_spin.return_to_base import audit_enabled, audit_blocked, pending_return

import itertools
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from tester_spin.models import Game, GameTestResult, SpinAttempt
from tester_spin.providers.belatra import BelatraProvider as _BelatraProvider
from tester_spin.providers.base import Progress


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_error(result: GameTestResult, message: str) -> None:
    clean = str(message or "").strip()
    if not clean or clean in str(result.error or ""):
        return
    result.error = (str(result.error or "").strip() + " " + clean).strip()


def _read_enter(result: GameTestResult) -> dict[str, Any]:
    root = Path(str(result.run_dir or ""))
    path = root / "bootstrap" / "enter.response.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _math_type_domain(gs: dict[str, Any]) -> list[int]:
    values: list[int] = []
    current = gs.get("mathType")
    if isinstance(current, (bool, int, float)):
        values.append(int(current))
    analytical = gs.get("analInfo")
    if isinstance(analytical, dict):
        for key, value in analytical.items():
            if not re.fullmatch(r"mathType[A-Za-z0-9_]+", str(key)):
                continue
            if isinstance(value, (bool, int, float)):
                number = int(value)
                if number not in values:
                    values.append(number)
    return values if len(values) >= 2 else []


def _selector_dimensions(gs: dict[str, Any]) -> list[tuple[str, list[int]]]:
    dimensions: list[tuple[str, list[int]]] = []

    vip = gs.get("vipMode")
    if isinstance(vip, dict):
        try:
            vip_multiplier = float(vip.get("vipBetK") or 0)
        except (TypeError, ValueError):
            vip_multiplier = 0.0
        if vip_multiplier > 1:
            dimensions.append(("vipOn", [0, 1]))

    for key, value in gs.items():
        name = str(key)
        if not re.fullmatch(r"isMath[A-Za-z0-9_]*", name):
            continue
        if isinstance(value, bool) or (
            isinstance(value, (int, float)) and int(value) in {0, 1}
        ):
            dimensions.append((name, [0, 1]))

    math_types = _math_type_domain(gs)
    if math_types:
        dimensions.append(("mathType", math_types))

    deduped: list[tuple[str, list[int]]] = []
    seen: set[str] = set()
    for name, values in dimensions:
        if name in seen:
            continue
        seen.add(name)
        deduped.append((name, list(dict.fromkeys(values))))
    return deduped


def _buy_bonus_options(gs: dict[str, Any]) -> list[str]:
    buy = gs.get("buyBonus")
    if not isinstance(buy, dict):
        return []
    raw = buy.get("buyTotalBetK")
    options: list[str] = []
    if isinstance(raw, dict):
        for key in raw:
            clean = str(key).strip()
            if clean and clean not in options:
                options.append(clean)
    elif isinstance(raw, list):
        for index, item in enumerate(raw):
            candidate = index
            clean = str(candidate).strip()
            if clean and clean not in options:
                options.append(clean)
    return options


def _combo_label(combo: dict[str, int]) -> str:
    if not combo:
        return "BASE"
    return "|".join(f"{key}={combo[key]}" for key in sorted(combo))


def _purchase_request(enter: dict[str, Any], option: str) -> dict[str, Any]:
    # Official v3 core all_content.f5ccaa85303b20361ec4.js builds start
    # with buyBonus=1 and selectId=justBuyBonusSelectType (the slide index).
    options = (enter.get("gs") or {}).get("buyBonus", {}).get("buyTotalBetK")
    if not isinstance(options, list) or option not in [str(i) for i in range(len(options))]:
        raise ValueError("Belatra purchase requires an advertised array index")
    request = _BelatraProvider._base_spin_request(enter)
    request.update(buyBonus=1, selectId=int(option), vipOn=0)
    return request


def _bonus_info(gs, category):
    values = gs.get("subGameInfo")
    if not isinstance(values, list):
        return None
    matches = [v for v in values if isinstance(v, dict) and v.get("category") == category]
    return matches[0] if len(matches) == 1 else None


def _server_integer(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _continuation_request(gs):
    """Select only controls demonstrated by official client and server state."""
    cur, nxt = str(gs.get("phaseCur") or ""), str(gs.get("phaseNext") or "")
    respin, free = gs.get("respinInfo"), gs.get("freeInfo")
    # Active respins take priority even when phaseNext remains toNextFG.
    if nxt in {"toRespin", "toNextFG"} and isinstance(respin, dict) and _server_integer(respin.get("nIt"), 1):
        return {"q": "play", "userAction": "askRespin"}
    if nxt == "toNextFG" and isinstance(free, dict) and _server_integer(free.get("remain"), 1):
        return {"q": "play", "userAction": "askNextFG", "remainFG": free["remain"]}
    if nxt in {"toPaid", "toDoubleDialog"}:
        return {"q": "finish", "ghistId": gs["historyId"]}
    if re.fullmatch(r"toBonus[0-9]+", nxt):
        category = nxt[2:]
        if not cur.startswith("Bonus"):
            return {"q": "play", "userAction": "ask" + category, "wasAttempt": 0}
        sub, other = _bonus_info(gs, category), gs.get("other")
        if (cur == category and sub is not None
                and isinstance(other, dict) and other.get("autochoice") == "start"
                and _server_integer(sub.get("attempt"), 1)
                and _server_integer(sub.get("respinRemain"), -1)
                and _server_integer(sub.get("startRespin"))
                and isinstance(sub.get("stopBox"), list) and sub["stopBox"]):
            return {"q": "play", "userAction": "ask" + category + "start", "wasAttempt": sub["attempt"]}
    return None


def _bonus_acknowledged(request, gs):
    match = re.fullmatch(r"ask(Bonus[0-9]+)(start)?", str(request.get("userAction") or ""))
    if match is None:
        return True
    category, choice = match.groups()
    sub = _bonus_info(gs, category)
    if sub is None or not _server_integer(sub.get("attempt"), 1):
        return False
    cur, nxt = gs.get("phaseCur"), gs.get("phaseNext")
    previous = request["wasAttempt"]
    if not choice:
        return cur == category and nxt == "to" + category and sub["attempt"] == 1
    if sub.get("userChoice") != choice:
        return False
    if cur == category and nxt == "to" + category:
        return sub["attempt"] == previous + 1
    return (cur == category + "_finished" and nxt == "toPaid"
            and sub["attempt"] in {previous, previous + 1}
            and _server_integer(sub.get("respinRemain"), -1)
            and sub["respinRemain"] <= 0)


def _continue_round(provider, state, response, *, timeout_s, artifact_dir, finish_label=None):
    """Complete demonstrated free/respin/automatic bonus paths, bounded."""
    steps = 1
    for _ in range(500):
        from tester_spin.return_to_base import audit_stop_event
        stop = audit_stop_event()
        if stop is not None and stop.is_set():
            raise InterruptedError("Detención solicitada")
        gs = response.get("gs") or {}
        cur, nxt = str(gs.get("phaseCur") or ""), str(gs.get("phaseNext") or "")
        if cur == "finished" and nxt == "toIdle":
            return True, steps, cur, nxt
        if gs.get("historyId") is None:
            raise RuntimeError("Belatra round response missing historyId")
        request = _continuation_request(gs)
        if request is None:
            return False, steps, cur, nxt
        label = finish_label if request["q"] == "finish" and finish_label else f"continue-{steps:03d}"
        response = provider._post_direct_game(state, request, timeout_s=timeout_s, artifact_dir=artifact_dir, label=label)
        steps += 1
        final = response.get("gs") or {}
        cur, nxt = str(final.get("phaseCur") or ""), str(final.get("phaseNext") or "")
        if not _bonus_acknowledged(request, final):
            return False, steps, cur, nxt
        if request["q"] == "finish":
            return cur == "finished" and nxt == "toIdle", steps, cur, nxt
    return False, steps, cur, nxt


def _gamble_round(provider, state, choice, *, timeout_s, artifact_dir, gamble_type="redblack", half=0):
    domain = {"Red", "Black", "Spade", "Club", "Heart", "Diamond"} if gamble_type == "redblack" else {"1", "2", "3", "4"} if gamble_type == "dealer" else set()
    if choice not in domain or half not in {0, 1}:
        raise ValueError("Unsupported Belatra gamble choice")
    def post(body, label):
        return provider._post_direct_game(state, body, timeout_s=timeout_s, artifact_dir=artifact_dir, label=label)
    def info(response):
        return next((v for v in response.get("gs", {}).get("subGameInfo", []) if v.get("category") == "Double" and v.get("type") == gamble_type), None)
    response = post({"q": "play", "userAction": "askDouble", "wasAttempt": 0, "dblhalf": half}, "gamble-enter")
    sub = info(response)
    if sub is None or "attempt" not in sub:
        raise RuntimeError("Gamble entered a non-redblack or unrecognized subgame")
    response = post({"q": "play", "userAction": "askDouble" + choice, "wasAttempt": sub["attempt"]}, "gamble-choice")
    selected = info(response)
    if selected is None or selected.get("attempt") != sub["attempt"] + 1 or str(selected.get("userChoice")) != choice:
        raise RuntimeError("Server did not acknowledge requested gamble choice and attempt")
    steps = 2
    if response.get("gs", {}).get("phaseNext") != "toPaid":
        sub = info(response)
        if sub is None or "attempt" not in sub:
            raise RuntimeError("Gamble result missing authoritative attempt")
        response = post({"q": "play", "userAction": "askDoubleBackToGame", "wasAttempt": sub["attempt"]}, "gamble-collect")
        steps += 1
    terminal, tail_steps, cur, nxt = _continue_round(provider, state, response, timeout_s=timeout_s, artifact_dir=artifact_dir)
    return terminal, steps + tail_steps - 1, cur, nxt


def _execute_gamble_choices(provider, game, choices, *, timeout_s, artifact_dir, stop_event, max_spins=None, gamble_type="redblack", half=0):
    outcomes = {choice: (False, 0, "", "NO_DOUBLE_EVENT", str(artifact_dir / f"unobserved-{choice}")) for choice in choices}
    state = None
    try:
        state = provider._open_direct_game(game, timeout_s=timeout_s, run_dir=artifact_dir / "bootstrap")
        if state["enter"].get("gs", {}).get("doubleActive") != gamble_type:
            if gamble_type not in state["enter"].get("gs", {}).get("doubleAssortment", []):
                return outcomes
            provider._post_direct_game(state, {"setting": json.dumps({"doublePrefer": gamble_type})}, timeout_s=timeout_s, artifact_dir=artifact_dir, label="gamble-setting")
            refreshed = provider._post_direct_game(state, {"q": "enter", "curFloor": 1}, timeout_s=timeout_s, artifact_dir=artifact_dir, label="gamble-setting-enter")
            if refreshed.get("gs", {}).get("doubleActive") != gamble_type:
                raise RuntimeError("Server did not confirm requested doublePrefer")
            state["enter"] = refreshed
        pending = list(choices)
        trigger_budget = max(36, 12 * len(choices)) if max_spins is None else max(0, int(max_spins))
        for number in range(trigger_budget):
            if not pending or stop_event.is_set() or audit_blocked():
                break
            attempt_dir = artifact_dir / f"trigger-{number:03d}"
            from tester_spin.server_observations import set_capture_directory
            set_capture_directory(attempt_dir)
            response = provider._post_direct_game(state, provider._base_spin_request(state["enter"]), timeout_s=timeout_s, artifact_dir=attempt_dir, label="start")
            gs = response.get("gs") or {}
            if gs.get("phaseNext") == "toDoubleDialog" and gs.get("curWin", 0) > 0:
                if "DECLINE" not in outcomes:
                    outcome = _continue_round(provider, state, response, timeout_s=timeout_s, artifact_dir=attempt_dir)
                    if audit_enabled():
                        from tester_spin.provider_return_checks import belatra_check
                        proof = belatra_check(provider, state, attempt_dir, timeout_s) if outcome[0] else pending_return(attempt_dir, "Decline Belatra no terminal")
                        outcome = (outcome[0] and proof['status'] == 'CONFIRMED', *outcome[1:])
                    outcomes["DECLINE"] = outcome
                    if not outcome[0]:
                        break
                    continue
                choice = pending.pop(0)
                outcome = _gamble_round(provider, state, choice, timeout_s=timeout_s, artifact_dir=attempt_dir, gamble_type=gamble_type, half=half)
                if audit_enabled():
                    from tester_spin.provider_return_checks import belatra_check
                    proof = belatra_check(provider, state, attempt_dir, timeout_s) if outcome[0] else pending_return(attempt_dir, "Gamble Belatra no terminal")
                    outcome = (outcome[0] and proof['status'] == 'CONFIRMED', *outcome[1:])
                outcomes[choice] = (*outcome, str(attempt_dir))
                _write_json(attempt_dir / "gamble-option.json", {"choice": choice, "terminal": outcome[0]})
            else:
                outcome = _continue_round(provider, state, response, timeout_s=timeout_s, artifact_dir=attempt_dir)
                if audit_enabled():
                    from tester_spin.provider_return_checks import belatra_check
                    proof = belatra_check(provider, state, attempt_dir, timeout_s) if outcome[0] else pending_return(attempt_dir, "Trigger Belatra no terminal")
                    outcome = (outcome[0] and proof['status'] == 'CONFIRMED', *outcome[1:])
            if not outcome[0]:
                break
    except Exception as exc:
        # Preserve already verified choices if a later trigger/choice fails.
        _write_json(artifact_dir / "error.json", {"error": f"{type(exc).__name__}: {exc}"})
        if audit_enabled():
            pending_return(artifact_dir, "Gamble Belatra interrumpido sin retorno confirmado")
    finally:
        _close_state(state)
    return outcomes


def _selector_matrix(
    dimensions: list[tuple[str, list[int]]],
) -> list[dict[str, int]]:
    if not dimensions:
        return [{}]
    names = [name for name, _values in dimensions]
    domains = [values for _name, values in dimensions]
    return [dict(zip(names, values)) for values in itertools.product(*domains)]


def _execute_gamble_samples(provider, game, choices, *, repetitions, artifact_dir, stop_event, **kwargs):
    samples = {choice: [] for choice in choices}
    samples["DECLINE"] = (False,)
    for repetition in range(1, max(1, int(repetitions)) + 1):
        if stop_event.is_set() or audit_blocked():
            break
        directory = artifact_dir / f"repetition-{repetition:03d}"
        outcomes = _execute_gamble_choices(provider, game, choices, artifact_dir=directory, stop_event=stop_event, **kwargs)
        if outcomes.get("DECLINE", (False,))[0]:
            samples["DECLINE"] = outcomes["DECLINE"]
        for choice in choices:
            samples[choice].append(outcomes[choice])
    return samples


def _record_gamble_samples(result, samples, choices, *, repetitions, prefix, attempt_number, artifact_dir):
    requested = successes = 0
    counts = {}
    for choice in choices:
        rows = samples.get(choice) or [(False, 0, "", "UNKNOWN", str(artifact_dir / f"unobserved-{choice}"))]
        counts[choice] = sum(int(row[0]) for row in rows)
        for ok, steps, cur, nxt, evidence_dir in rows:
            attempt_number += 1
            requested += 1
            successes += int(ok)
            result.attempts.append(SpinAttempt(number=attempt_number, ok=ok, terminal=ok, mode_id=f"GAMBLE__{prefix}{choice}", mode_kind="CHOICE_BRANCH", wire_steps=steps, na=nxt, artifact_dir=evidence_dir, warning="" if ok else "Gamble no cubierto: evento ausente o fase no terminal"))
    covered = [choice for choice in choices if counts[choice] >= max(1, int(repetitions))]
    return attempt_number, requested, successes, covered, counts


def _base_combo(provider: _BelatraProvider, enter: dict[str, Any], dimensions) -> dict[str, int]:
    request = provider._base_spin_request(enter)
    return {
        name: int(request[name])
        for name, _values in dimensions
        if isinstance(request.get(name), (bool, int, float))
    }


def _close_state(state: dict[str, Any] | None) -> None:
    if not isinstance(state, dict):
        return
    session = state.get("session")
    try:
        if session is not None:
            session.close()
    except Exception:
        pass


def _execute_selector_variant(
    provider: _BelatraProvider,
    game: Game,
    *,
    combo: dict[str, int],
    timeout_s: float,
    artifact_dir: Path,
) -> tuple[bool, int, str, str, bool]:
    from tester_spin.server_observations import set_capture_directory
    set_capture_directory(artifact_dir)
    state: dict[str, Any] | None = None
    started = time.monotonic()
    try:
        state = provider._open_direct_game(
            game,
            timeout_s=timeout_s,
            run_dir=artifact_dir / "bootstrap",
        )
        request = provider._base_spin_request(state["enter"])
        for key, value in combo.items():
            request[key] = int(value)
        start = provider._post_direct_game(
            state,
            request,
            timeout_s=timeout_s,
            artifact_dir=artifact_dir,
            label="start",
        )
        gs = start.get("gs")
        if not isinstance(gs, dict):
            raise RuntimeError("Belatra selector variant: start sin gs.")
        phase_cur = str(gs.get("phaseCur") or "")
        phase_next = str(gs.get("phaseNext") or "")
        history_id = gs.get("historyId")
        saw_double_dialog = phase_next == "toDoubleDialog"
        if history_id is None:
            raise RuntimeError("Belatra selector variant: start sin historyId.")
        terminal, steps, final_cur, final_next = _continue_round(
            provider, state, start, timeout_s=timeout_s,
            artifact_dir=artifact_dir, finish_label="finish",
        )
        if audit_enabled():
            from tester_spin.provider_return_checks import belatra_check
            proof = belatra_check(provider, state, artifact_dir, timeout_s) if terminal else pending_return(artifact_dir, 'Variante Belatra no terminal')
            terminal = terminal and proof['status'] == 'CONFIRMED'
        return terminal, steps, final_cur, final_next, saw_double_dialog
    finally:
        _close_state(state)
        _write_json(
            artifact_dir / "variant.json",
            {
                "selectors": combo,
                "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
            },
        )


def _base_saw_double_dialog(result: GameTestResult) -> bool:
    for attempt in result.attempts:
        if not attempt.artifact_dir:
            continue
        path = Path(attempt.artifact_dir) / "start.response.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        gs = payload.get("gs") if isinstance(payload, dict) else None
        if isinstance(gs, dict) and str(gs.get("phaseNext") or "") == "toDoubleDialog":
            return True
    return False


def expand_belatra_paths(
    provider: _BelatraProvider,
    game: Game,
    result: GameTestResult,
    *,
    repetitions: int,
    timeout_s: float,
    stop_event: threading.Event,
    progress: Progress,
) -> GameTestResult:
    if result.status in {"ERROR", "CANCELADO"} or not result.run_dir:
        return result

    enter = _read_enter(result)
    gs = enter.get("gs") if isinstance(enter, dict) else None
    if not isinstance(gs, dict):
        return result

    run_root = Path(result.run_dir)
    dimensions = _selector_dimensions(gs)
    matrix = _selector_matrix(dimensions)
    base_combo = _base_combo(provider, enter, dimensions)
    base_label = _combo_label(base_combo)
    required = [_combo_label(combo) for combo in matrix]
    covered: set[str] = set()

    base_attempts = [attempt for attempt in result.attempts if attempt.mode_id == "SPIN"]
    base_ok = bool(base_attempts) and all(attempt.ok and attempt.terminal for attempt in base_attempts)
    if base_ok and base_label in required:
        covered.add(base_label)

    attempt_number = max((attempt.number for attempt in result.attempts), default=0)
    added_requested = 0
    added_successes = 0
    saw_double = _base_saw_double_dialog(result)

    for combo in matrix:
        if stop_event.is_set() or audit_blocked():
            break
        label = _combo_label(combo)
        if label == base_label:
            continue
        variant_all_ok = True
        for repetition in range(1, max(1, int(repetitions)) + 1):
            if stop_event.is_set() or audit_blocked():
                variant_all_ok = False
                break
            attempt_number += 1
            added_requested += 1
            attempt_dir = (
                run_root
                / "branch-coverage"
                / "belatra-start-selectors"
                / label.replace("|", "__").replace("=", "-")
                / f"attempt-{repetition:04d}"
            )
            started = time.monotonic()
            try:
                terminal, steps, phase_cur, phase_next, branch_double = _execute_selector_variant(
                    provider,
                    game,
                    combo=combo,
                    timeout_s=timeout_s,
                    artifact_dir=attempt_dir,
                )
                saw_double = saw_double or branch_double
                ok = bool(terminal)
                variant_all_ok = variant_all_ok and ok
                added_successes += int(ok)
                attempt = SpinAttempt(
                    number=attempt_number,
                    ok=ok,
                    mode_id=f"SPIN__{label}",
                    mode_kind="SPIN_VARIANT",
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                    symbol=result.symbol,
                    endpoint="/game",
                    na=phase_next,
                    terminal=terminal,
                    wire_steps=steps,
                    warning="" if ok else f"Belatra selector variant no terminal: {phase_cur}/{phase_next}",
                    artifact_dir=str(attempt_dir),
                )
            except Exception as exc:
                variant_all_ok = False
                attempt = SpinAttempt(
                    number=attempt_number,
                    ok=False,
                    mode_id=f"SPIN__{label}",
                    mode_kind="SPIN_VARIANT",
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                    symbol=result.symbol,
                    endpoint="/game",
                    terminal=False,
                    error=f"{type(exc).__name__}: {exc}",
                    artifact_dir=str(attempt_dir),
                )
            result.attempts.append(attempt)
            progress(
                f"[{game.name}] Belatra variante {label} {repetition}/{max(1, int(repetitions))}: "
                f"{'OK' if attempt.ok else 'PARCIAL'}"
            )
        if variant_all_ok:
            covered.add(label)

    if dimensions:
        result.discovered_modes.append(
            {
                "id": "BELATRA_START_SELECTOR_MATRIX",
                "kind": "CHOICE_BRANCH",
                "observed": True,
                "executable": True,
                "wire_command": "start",
                "coverage_required": True,
                "branch_signature": "BELATRA:start-selector-matrix",
                "dimensions": [
                    {"field": name, "values": values}
                    for name, values in dimensions
                ],
                "required_options": required,
                "covered_options": sorted(covered),
            }
        )

    from tester_spin.feature_domains import initialization_domains
    result.feature_domains = initialization_domains("belatra", gs, result.discovered_modes)
    buy_options = _buy_bonus_options(gs)
    buy_covered = []
    buy_executable = isinstance((gs.get("buyBonus") or {}).get("buyTotalBetK"), list)
    if buy_options and buy_executable:
        for option in buy_options:
            option_ok = True
            for repetition in range(1, max(1, int(repetitions)) + 1):
                if stop_event.is_set() or audit_blocked():
                    option_ok = False
                    break
                attempt_number += 1
                added_requested += 1
                attempt_dir = run_root / "branch-coverage" / "belatra-buy-bonus" / option / f"attempt-{repetition:04d}"
                state = None
                attempt = SpinAttempt(number=attempt_number, ok=False, mode_id=f"BUY_BONUS__{option}", mode_kind="PURCHASE", artifact_dir=str(attempt_dir))
                try:
                    from tester_spin.server_observations import set_capture_directory
                    set_capture_directory(attempt_dir)
                    state = provider._open_direct_game(game, timeout_s=timeout_s, run_dir=attempt_dir / "bootstrap")
                    response = provider._post_direct_game(state, _purchase_request(state["enter"], option), timeout_s=timeout_s, artifact_dir=attempt_dir, label="start")
                    terminal, steps, cur, nxt = _continue_round(provider, state, response, timeout_s=timeout_s, artifact_dir=attempt_dir)
                    if audit_enabled():
                        from tester_spin.provider_return_checks import belatra_check
                        proof = belatra_check(provider, state, attempt_dir, timeout_s) if terminal else pending_return(attempt_dir, "Compra Belatra no terminal")
                        terminal = terminal and proof['status'] == 'CONFIRMED'
                    attempt.ok = attempt.terminal = terminal
                    attempt.wire_steps, attempt.na = steps, nxt
                    if not terminal:
                        attempt.warning = f"Compra Belatra no terminal: {cur}/{nxt}"
                except Exception as exc:
                    attempt.error = f"{type(exc).__name__}: {exc}"
                finally:
                    _close_state(state)
                result.attempts.append(attempt)
                added_successes += int(attempt.ok)
                option_ok = option_ok and attempt.ok
                progress(f"[{game.name}] Belatra compra {option}: {'OK' if attempt.ok else 'PARCIAL'}")
            if option_ok:
                buy_covered.append(option)
    if buy_options:
        result.discovered_modes.append(
            {
                "id": "BELATRA_BUY_BONUS",
                "kind": "PURCHASE_BRANCH",
                "observed": True,
                "executable": buy_executable,
                "coverage_required": True,
                "branch_signature": "BELATRA:buyBonus.buyTotalBetK",
                "required_options": buy_options,
                "covered_options": buy_covered,
                "reason": "Contrato start buyBonus=1/selectId=index del cliente oficial v3; fases desconocidas quedan pendientes" if buy_executable else "Formato de compra no demostrado en cliente oficial",
            }
        )

    gamble_options = []
    gamble_covered = []
    if gs.get("doubleActive") == "redblack" or "redblack" in gs.get("doubleAssortment", []):
        gamble_options = ["Red", "Black"]
        if gs.get("doubleNoSuits") is None:
            gamble_options += ["Spade", "Club", "Heart", "Diamond"]
        gamble_dir = run_root / "branch-coverage" / "belatra-gamble-redblack"
        try:
            outcomes = _execute_gamble_samples(provider, game, gamble_options, repetitions=repetitions, timeout_s=timeout_s, artifact_dir=gamble_dir, stop_event=stop_event)
        except Exception as exc:
            outcomes = {}
            _write_json(gamble_dir / "error.json", {"error": f"{type(exc).__name__}: {exc}"})
        saw_double = saw_double or outcomes.get("DECLINE", (False,))[0]
        attempt_number, requested_count, success_count, gamble_covered, counts = _record_gamble_samples(result, outcomes, gamble_options, repetitions=repetitions, prefix="", attempt_number=attempt_number, artifact_dir=gamble_dir)
        added_requested += requested_count
        added_successes += success_count
        progress(f"[{game.name}] Belatra gamble redblack full: {len(gamble_covered)}/{len(gamble_options)} opciones")
        result.discovered_modes.append({"id": "BELATRA_DOUBLE_REDBLACK", "kind": "CHOICE_BRANCH", "observed": True, "executable": True, "coverage_required": True, "branch_signature": "BELATRA:Double:redblack:full", "required_options": list(gamble_options), "covered_options": list(gamble_covered), "required_samples": max(1, int(repetitions)), "sample_counts": counts})
    double_types = [str(value) for value in gs.get("doubleAssortment", []) if value != "off"]
    group_complete = {"redblack:0": bool(gamble_options) and len(gamble_covered) == len(gamble_options)}
    for gamble_type, half in [("redblack", 1), ("dealer", 0), ("dealer", 1)]:
        if gamble_type not in double_types:
            continue
        options = (["Red", "Black"] + (["Spade", "Club", "Heart", "Diamond"] if gs.get("doubleNoSuits") is None else [])) if gamble_type == "redblack" else ["1", "2", "3", "4"]
        group = f"{gamble_type}:{half}"
        gamble_dir = run_root / "branch-coverage" / f"belatra-gamble-{gamble_type}-half-{half}"
        try:
            outcomes = _execute_gamble_samples(provider, game, options, repetitions=repetitions, timeout_s=timeout_s, artifact_dir=gamble_dir, stop_event=stop_event, gamble_type=gamble_type, half=half)
        except Exception as exc:
            outcomes = {}
            _write_json(gamble_dir / "error.json", {"error": f"{type(exc).__name__}: {exc}"})
        saw_double = saw_double or outcomes.get("DECLINE", (False,))[0]
        attempt_number, requested_count, success_count, group_covered, counts = _record_gamble_samples(result, outcomes, options, repetitions=repetitions, prefix=f"{group}:", attempt_number=attempt_number, artifact_dir=gamble_dir)
        added_requested += requested_count
        added_successes += success_count
        gamble_options.extend(f"{group}:{option}" for option in options)
        gamble_covered.extend(f"{group}:{option}" for option in group_covered)
        progress(f"[{game.name}] Belatra gamble {group}: {len(group_covered)}/{len(options)} opciones")
        group_complete[group] = len(group_covered) == len(options)
        result.discovered_modes.append({"id": f"BELATRA_DOUBLE_{gamble_type.upper()}_HALF_{half}", "kind": "CHOICE_BRANCH", "observed": True, "executable": True, "coverage_required": True, "branch_signature": f"BELATRA:Double:{group}", "required_options": options, "covered_options": group_covered, "required_samples": max(1, int(repetitions)), "sample_counts": counts})
    covered_double_types = [kind for kind in double_types if group_complete.get(f"{kind}:0") and group_complete.get(f"{kind}:1")]
    if double_types:
        result.discovered_modes.append({"id": "BELATRA_DOUBLE_TYPES", "kind": "CHOICE_BRANCH", "observed": True, "executable": all(kind in {"redblack", "dealer"} for kind in double_types), "coverage_required": True, "branch_signature": "BELATRA:doubleAssortment", "required_options": double_types, "covered_options": covered_double_types, "reason": "Tipos dealer/redblack con apuesta completa y mitad; cobertura requiere todas sus opciones"})
    if saw_double or gamble_options:
        result.discovered_modes.append(
            {
                "id": "BELATRA_DOUBLE_DIALOG",
                "kind": "CHOICE_BRANCH",
                "observed": True,
                "executable": bool(gamble_options),
                "coverage_required": True,
                "branch_signature": "BELATRA:toDoubleDialog",
                "required_options": ["DECLINE", "GAMBLE"],
                "covered_options": (["DECLINE"] if saw_double else []) + (["GAMBLE"] if gamble_covered else []),
                "reason": "Contrato de cliente oficial; opciones y tipos auditados individualmente",
            }
        )

    result.requested_spins += added_requested
    result.successful_spins += added_successes
    result.failed_spins = max(0, result.requested_spins - result.successful_spins)
    missing_selector = [option for option in required if option not in covered]
    unresolved = []
    if missing_selector:
        unresolved.append("selectores start: " + ", ".join(missing_selector))
    missing_buy = [option for option in buy_options if option not in buy_covered]
    if missing_buy:
        unresolved.append("buy bonus: " + ", ".join(missing_buy))
    if (saw_double or gamble_options) and not gamble_covered:
        unresolved.append("gamble de toDoubleDialog")
    missing_gamble = [option for option in gamble_options if option not in gamble_covered]
    if missing_gamble:
        unresolved.append("gamble redblack: " + ", ".join(missing_gamble))
    if gamble_options and not saw_double:
        unresolved.append("decline de toDoubleDialog")
    missing_double_types = [value for value in double_types if value not in covered_double_types]
    if missing_double_types:
        unresolved.append("tipos gamble: " + ", ".join(missing_double_types))
    if unresolved and result.status == "OK":
        result.status = "PARCIAL"
    if unresolved:
        _append_error(result, "Belatra cobertura exhaustiva pendiente: " + "; ".join(unresolved) + ".")

    _write_json(run_root / "result.json", result.to_dict())
    return result


class BelatraProvider(_BelatraProvider):
    """Belatra with HAR-grounded exhaustive selector coverage."""

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
        return expand_belatra_paths(
            self,
            game,
            result,
            repetitions=max(1, int(spins)),
            timeout_s=timeout_s,
            stop_event=stop_event,
            progress=progress,
        )


__all__ = ["BelatraProvider", "expand_belatra_paths"]
