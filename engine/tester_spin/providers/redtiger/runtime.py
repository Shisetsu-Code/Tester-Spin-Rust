from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import requests

from tester_spin.providers.redtiger.result_tree import observed_modes, result_nodes, walk_tree


@dataclass(frozen=True, slots=True)
class FeatureBuy:
    name: str
    multiplier: Decimal


@dataclass(frozen=True, slots=True)
class ChoicePrompt:
    round_id: int | str
    available: tuple[str, ...]
    selected: str | None = None


@dataclass(slots=True)
class RedTigerRuntime:
    session: requests.Session
    settings_url: str
    spin_url: str
    launcher_url: str
    game_id: str
    session_id: str
    token: str
    user_data: dict[str, Any]
    custom: dict[str, Any]
    settings_request: dict[str, Any]
    settings_response: dict[str, Any]
    stakes: tuple[Decimal, ...]
    default_stake: Decimal
    currency_decimals: int
    feature_buys: tuple[FeatureBuy, ...]
    # Session-specific client evidence, separate from advertised settings contracts.
    client_observed_feature_buys: tuple[str, ...] = ()


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def settings_result(settings_response: dict[str, Any]) -> dict[str, Any]:
    if settings_response.get("success") is not True:
        raise ValueError("Red Tiger settings no devolvió success=true.")
    result = settings_response.get("result")
    if not isinstance(result, dict):
        raise ValueError("Red Tiger settings no contiene result objeto.")
    if not isinstance(result.get("game"), dict):
        raise ValueError("Red Tiger settings no contiene result.game objeto.")
    if not isinstance(result.get("user"), dict):
        raise ValueError("Red Tiger settings no contiene result.user objeto.")
    return result


def stakes_from_settings(settings_response: dict[str, Any]) -> tuple[tuple[Decimal, ...], Decimal]:
    result = settings_result(settings_response)
    user = result["user"]
    stake_info = user.get("stakes")
    if not isinstance(stake_info, dict):
        raise ValueError("Red Tiger settings no anunció user.stakes.")

    raw_types = stake_info.get("types")
    if not isinstance(raw_types, list):
        raise ValueError("Red Tiger settings user.stakes.types no es lista.")

    stakes: list[Decimal] = []
    for raw in raw_types:
        value = _decimal(raw)
        if value is not None and value > 0 and value not in stakes:
            stakes.append(value)
    if not stakes:
        raise ValueError("Red Tiger settings no anunció stakes positivos.")

    default_index = stake_info.get("defaultIndex")
    if not isinstance(default_index, int) or isinstance(default_index, bool):
        default_index = stake_info.get("lastIndex")
    if not isinstance(default_index, int) or isinstance(default_index, bool):
        default_index = 0
    if default_index < 0 or default_index >= len(stakes):
        default_index = 0
    return tuple(stakes), stakes[default_index]


def feature_buys_from_settings(settings_response: dict[str, Any]) -> tuple[FeatureBuy, ...]:
    game = settings_result(settings_response)["game"]
    if game.get("hasFeatureBuy") is False:
        return ()
    raw = game.get("featureBuy")
    if not isinstance(raw, list):
        return ()

    found: list[FeatureBuy] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        multiplier = _decimal(item.get("price"))
        if not name or multiplier is None or multiplier <= 0:
            continue
        candidate = FeatureBuy(name=name, multiplier=multiplier)
        if candidate not in found:
            found.append(candidate)
    return tuple(found)


def purchase_declaration(game: Any) -> dict[str, Any]:
    """Require the enabled current settings contract, corroborated by math modes."""
    domain = {'complete': False, 'source': 'SETTINGS.game.hasFeatureBuy/featureBuy/mathModes', 'options': []}
    if not isinstance(game, dict):
        return domain
    if game.get('hasFeatureBuy') is False:
        domain['complete'] = True
        return domain
    if game.get('hasFeatureBuy') is not True:
        return domain
    def contracts(items, math=False):
        if not isinstance(items, list) or not items:
            return None
        found = {}
        for item in items:
            if not isinstance(item, dict):
                return None
            if math and item.get('type') in ('chanceIncrease','stateSwitch'):
                continue
            if math and item.get('type') != 'featureBuy':
                return None
            name = item.get('name')
            raw_price = item.get('priceMultiplier' if math else 'price')
            price = None if isinstance(raw_price, bool) else _decimal(raw_price)
            if not isinstance(name, str) or not name.strip() or name != name.strip() or price is None or price <= 0 or name in found:
                return None
            found[name] = price
        return found
    advertised = contracts(game.get('featureBuy'))
    effective = contracts(game.get('mathModes'), math=True)
    if advertised and advertised == effective:
        domain.update(complete=True, options=list(advertised))
    return domain


def decimal_json_number(value: Decimal) -> int | float:
    integral = value.to_integral_value()
    if value == integral:
        return int(integral)
    return float(value)


def money_string(value: Decimal, decimals: int) -> str:
    places = max(0, min(8, int(decimals)))
    quantum = Decimal(1).scaleb(-places)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{rounded:.{places}f}"


def build_spin_payload(
    runtime: RedTigerRuntime,
    *,
    stake: Decimal,
    feature_buy: FeatureBuy | None = None,
    game_mode: int | str = 0,
) -> dict[str, Any]:
    if stake not in runtime.stakes:
        raise ValueError(f"Red Tiger stake no anunciado por settings: {stake!s}.")

    payload = {
        "token": runtime.token,
        "sessionId": runtime.session_id,
        "playMode": str(runtime.settings_request.get("playMode") or "demo"),
        "gameId": runtime.game_id,
        "userData": copy.deepcopy(runtime.user_data),
        "custom": copy.deepcopy(runtime.custom),
        "stake": decimal_json_number(stake),
        "listenToFrontend": bool(runtime.settings_request.get("listenToFrontend", True)),
        "bonusId": None,
        "extras": None,
        "gameMode": game_mode,
    }
    if feature_buy is not None:
        cost = stake * feature_buy.multiplier
        payload["extras"] = {
            "features": {
                "featureBuy": feature_buy.name,
                "featureBuyCost": money_string(cost, runtime.currency_decimals),
            }
        }
    return payload


def choice_state(payload: Any) -> dict[str, Any]:
    result = payload.get('result') if isinstance(payload, dict) else None
    game = result.get('game') if isinstance(result, dict) else None
    if not isinstance(game, dict) or game.get('choices') is None:
        return {'status': 'NONE'}
    raw = game['choices']
    unknown = {'status': 'UNKNOWN'}
    if not isinstance(raw, dict) or 'selected' not in raw or 'available' not in raw:
        return unknown
    selected, available = raw.get('selected'), raw.get('available')
    transactions = result.get('transactions')
    round_id = transactions.get('roundId') if isinstance(transactions, dict) else None
    state = {'status': 'UNKNOWN', 'round_id': round_id, 'selected': selected,
             'available': available, 'has_state': game.get('hasState')}
    if selected is None and isinstance(available, list) and available:
        if (all(isinstance(v, str) and v.strip() and v == v.strip() for v in available)
                and len(set(available)) == len(available)
                and (type(round_id) is int and round_id > 0 or isinstance(round_id, str) and round_id.strip())):
            state['status'] = 'PENDING'
    elif isinstance(selected, str) and selected.strip() and available in (None, []):
        state['status'] = 'RESOLVED'
    return state


def pending_choice_from_response(payload: Any) -> ChoicePrompt | None:
    if not isinstance(payload, dict) or payload.get('success') is not True:
        return None
    state = choice_state(payload)
    if state['status'] == 'PENDING':
        return ChoicePrompt(round_id=state['round_id'], available=tuple(state['available']))
    return None


def choice_reply_warnings(prompt, selected, payload):
    state = choice_state(payload)
    result = payload.get('result') or {}
    transactions = result.get('transactions')
    round_id = transactions.get('roundId') if isinstance(transactions, dict) else None
    warnings = []
    if type(round_id) is not type(prompt.round_id) or round_id != prompt.round_id:
        warnings.append('choice devolvió una ronda distinta de la solicitada')
    if state['status'] == 'UNKNOWN':
        warnings.append('choice devolvió un selector sin contrato reconocido')
    if state['status'] == 'RESOLVED' and state['selected'] != selected:
        warnings.append('choice confirmó una selección distinta de la solicitada')
    return warnings


def resolved_pickers(payload):
    result = payload.get('result') if isinstance(payload, dict) else {}
    game = result.get('game') if isinstance(result, dict) else {}
    found = []
    for path, value in walk_tree(game):
        if not isinstance(value, dict) or 'picker' not in value:
            continue
        picker = value['picker']
        record = {'path': path + '.picker', 'status': 'UNKNOWN', 'data': picker}
        if isinstance(picker, dict) and isinstance(picker.get('options'), list) and isinstance(picker.get('choices'), list):
            resolved = []
            for choice in picker['choices']:
                index = choice.get('option') if isinstance(choice, dict) else None
                if type(index) is not int or not 0 <= index < len(picker['options']):
                    break
                option = picker['options'][index]
                if not isinstance(option, dict) or option.get('name') != choice.get('name'):
                    break
                resolved.append({'index': index, 'name': option.get('name'), 'value': option.get('value')})
            else:
                record.update(status='RESOLVED', resolved=resolved)
        found.append(record)
    return found


def choice_transition(prompt, selected, payload):
    result = payload.get('result') or {}
    game = result.get('game') or {}
    state = choice_state(payload)
    data = game.get('gameData') or {}
    if not isinstance(data, dict):
        data = {}
    progress = data.get('progress') if isinstance(data, dict) else None
    level = progress.get('level') if isinstance(progress, dict) else None
    recurring = (state['status'] == 'PENDING' and state.get('available') == list(prompt.available)
                 and state.get('round_id') == prompt.round_id and data.get('selected') == selected
                 and data.get('spinMode') == 'Normal' and isinstance(level, dict)
                 and type(level.get('current')) is int and type(level.get('next')) is int
                 and 0 <= level['current'] < level['next'])
    return {'round_id': prompt.round_id, 'available': list(prompt.available),
            'selected': selected, 'response_choice': state, 'recurring_selector': recurring,
            'game_data': sanitize_payload(game.get('gameData')),
            'resolved_pickers': resolved_pickers(payload)}


def choice_url_from_spin_url(spin_url: str) -> str:
    clean = str(spin_url or "").strip()
    if not clean or "/" not in clean:
        raise ValueError("Red Tiger spin_url inválido para derivar endpoint choice.")
    base, _, leaf = clean.rpartition("/")
    if leaf != "spin":
        raise ValueError("Red Tiger spin_url no termina en /spin.")
    return base + "/choice"


def build_choice_payload(
    runtime: RedTigerRuntime,
    *,
    prompt: ChoicePrompt,
    choice: str,
) -> dict[str, Any]:
    selected = str(choice or "").strip()
    if not selected or selected not in prompt.available:
        raise ValueError(f"Red Tiger choice no anunciado por el servidor: {selected!r}.")
    return {
        "token": runtime.token,
        "sessionId": runtime.session_id,
        "playMode": str(runtime.settings_request.get("playMode") or "demo"),
        "gameId": runtime.game_id,
        "userData": copy.deepcopy(runtime.user_data),
        "custom": copy.deepcopy(runtime.custom),
        "roundId": prompt.round_id,
        "choice": selected,
        "listenToFrontend": bool(runtime.settings_request.get("listenToFrontend", True)),
    }


def validate_spin_response(payload: Any) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return False, ["respuesta no es objeto JSON"]
    if payload.get("success") is not True:
        return False, [f"success={payload.get('success')!r}"]
    result = payload.get("result")
    if not isinstance(result, dict):
        return False, ["falta result objeto"]
    game = result.get("game")
    if not isinstance(game, dict):
        return False, ["falta result.game objeto"]
    if choice_state(payload)["status"] == "UNKNOWN":
        warnings.append("selector remoto sin contrato reconocido")
    if not result_nodes(game):
        warnings.append("resultado sin nodos spinMode observables")
    return True, warnings


def apply_response_token(runtime: RedTigerRuntime, payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    result = payload.get("result")
    if not isinstance(result, dict):
        return
    user = result.get("user")
    if not isinstance(user, dict):
        return
    token = str(user.get("token") or "").strip()
    session_id = str(user.get("sessionId") or "").strip()
    if token:
        runtime.token = token
    if session_id:
        runtime.session_id = session_id


def response_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"success": False, "spin_modes": [], "nodes": [], "pending_choice": None}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    game = result.get("game") if isinstance(result.get("game"), dict) else {}
    nodes = result_nodes(game)
    prompt = pending_choice_from_response(payload)
    return {
        "success": payload.get("success") is True,
        "spin_modes": observed_modes(game),
        "nodes": [
            {
                "path": node.path,
                "spin_mode": node.spin_mode,
                "game_mode": node.game_mode,
                "has_state": node.has_state,
                "feature_count": node.feature_count,
            }
            for node in nodes
        ],
        "choice_state": choice_state(payload),
        "resolved_pickers": resolved_pickers(payload),
        "pending_choice": (
            {
                "round_id": prompt.round_id,
                "available": list(prompt.available),
            }
            if prompt is not None
            else None
        ),
    }


def sanitize_payload(value: Any) -> Any:
    sensitive = {
        "token",
        "sessionid",
        "ne_evo_token",
        "wrapper_token",
        "fingerprint",
        "cookie",
        "authorization",
    }
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            if str(key).lower() in sensitive:
                clean[str(key)] = "<redacted>" if child not in {None, ""} else child
            else:
                clean[str(key)] = sanitize_payload(child)
        return clean
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


def purchase_executed(payload: Any, request: Any, feature: FeatureBuy) -> bool:
    """Require charged declared cost plus returned bonus/choice outcome."""
    if not isinstance(payload, dict) or payload.get('success') is not True:
        return False
    try:
        sent = request['extras']['features']
        stake = _decimal(request['stake'])
        cost = _decimal(sent['featureBuyCost'])
        if stake is None or stake <= 0 or cost is None or cost != stake * feature.multiplier or sent['featureBuy'] != feature.name:
            return False
        cash = payload['result']['user']['balance']['cash']
        start, after = _decimal(cash['atStart']), _decimal(cash['afterBet'])
        if start is None or after is None or start - after != cost:
            return False
        game = payload['result']['game']
        return any(node.feature_count > 0 for node in result_nodes(game)) or pending_choice_from_response(payload) is not None
    except (KeyError, TypeError, AttributeError):
        return False
