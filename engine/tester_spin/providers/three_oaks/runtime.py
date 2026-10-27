"""Goreel command transport. Discovery never substitutes for remote proof."""
import json
import re
import time
import uuid
from pathlib import Path


def observed_spin_profile(game_slug: str, family: str) -> dict | None:
    rules = json.loads(Path(__file__).with_name('observed_game_rules.json').read_text(encoding='utf-8'))
    if rules.get('schema') != 'three-oaks/observed-spin-inputs/v1':
        raise ValueError('3 Oaks: esquema de reglas desconocido')
    profile = rules.get('games', {}).get(game_slug)
    if (isinstance(profile, dict) and profile.get('family') == family
            and profile.get('spin_params') == ['bet_per_line', 'lines']
            and profile.get('evidence')):
        return profile
    return None


def checked_response(response) -> dict:
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("3 Oaks: respuesta no es objeto")
    status = data.get("status")
    if not isinstance(status, dict) or str(status.get("code", "")).upper() != "OK" or str(status.get("type", "ok")).lower() != "ok":
        raise ValueError("3 Oaks: " + str(status.get("code", "INVALID_STATUS") if isinstance(status, dict) else "INVALID_STATUS"))
    return data


def base_terminal(data: dict) -> bool:
    context = data.get("context", {})
    return (isinstance(context, dict) and context.get("round_finished") is True
            and context.get("current") == "spins" and "spin" in context.get("actions", []))


def discover_modes(data: dict, family: str, serializer_observed: bool, *, client_profile=None) -> list[dict]:
    context, settings = data.get("context", {}), data.get("settings", {})
    usable = serializer_observed and family in {"enjoy", "goreel", "ratpack", "hraymo", "kendoo"}
    modes = [{"id": "SPIN", "kind": "SPIN", "executable": usable, "validated": False,
              "observed": False, "source": "server-start", "family": family,
              "wire_action": "spin", "wire_command": "play", "coverage_required": True,
              "required_options": ["spin"], "covered_options": [], "sample_counts": {}}]
    values = context.get("available_buy_bonus", [])
    prices = settings.get("buy_bonus_prices", {})
    if isinstance(values, list):
        for value in values:
            if not isinstance(value, (int, str)) or isinstance(value, bool):
                continue
            modes.append({"id": f"PURCHASE_{value}", "kind": "PURCHASE", "executable": usable,
                "validated": False, "observed": False, "coverage_required": True,
                "source": "server-start", "family": family, "wire_action": "buy_spin", "wire_command": "play",
                "required_options": [str(value)], "covered_options": [], "sample_counts": {},
                "selected_mode": value,
                "request_options": {"selected_mode": value}, "feature_multiplier": prices.get(str(value)) if isinstance(prices, dict) else None})
    profile = client_profile or {}
    if profile.get('antebet_ui_observed'):
        for coefficient in profile.get('antebet_values', []):
            modes.append({'id':f'ANTE_BET_{coefficient}', 'kind':'ANTE_BET',
                          'executable':bool(profile.get('antebet_executable')), 'validated':False,
                          'observed':False,'client_observed':True,'coverage_required':True,
                          'source':'current-client-input-calls','wire_action':'spin','wire_command':'play',
                          'ante_bet':coefficient,'request_options':{'ante_bet':coefficient},
                          'required_options':[str(coefficient)],'covered_options':[],'sample_counts':{}})
    # Other purchase/booster formats remain visible and unimplemented.
    for key in ("available_boosters", "available_buy_freespins"):
        values = context.get(key)
        if values:
            modes.append({"id": key.upper(), "kind": "UNKNOWN_FEATURE", "executable": False,
                          "validated": False, "coverage_required": True, "required_options": values,
                          "reason": "WIRE_FORMAT_CAPTURE_REQUIRED"})
    return modes


def play_fields(data: dict, action: str, selected_mode=None, *, game_slug='', family='', client_profile=None, antebet=None) -> dict:
    context, settings = data["context"], data.get("settings", {})
    if action not in context.get("actions", []):
        raise ValueError("3 Oaks: acción no anunciada")
    params = {}
    if action in {"spin", "buy_spin"}:
        state = context.get(context.get("current"), {})
        factor = settings.get("bet_factor")
        profile = client_profile or {}
        captured_spin = action == 'spin' and profile.get('spin_params') == ['bet_per_line', 'lines']
        purchase_params = profile.get('purchase_params', {}).get(str(selected_mode)) if action == 'buy_spin' else None
        if purchase_params is not None:
            if (not isinstance(purchase_params, list) or not {'bet_per_line', 'lines'}.issubset(purchase_params)
                    or set(purchase_params) - {'bet_per_line', 'lines', 'bet_factor', 'selected_mode', 'ante_bet', 'buy_spin_scatters_count', 'paid_feature'}):
                raise ValueError('3 Oaks: contrato de compra inválido')
            if not {'selected_mode','buy_spin_scatters_count','paid_feature'}.intersection(purchase_params) and context.get('available_buy_bonus') != [selected_mode]:
                raise ValueError('3 Oaks: compra sin selector ambigua')
        if not all(isinstance(state.get(k), (int, float)) and not isinstance(state.get(k), bool) and (state[k] > 0 or (k == "lines" and state[k] == 0 and 0 in settings.get("lines", []))) for k in ("bet_per_line", "lines")):
            raise ValueError("3 Oaks: perfil de apuesta pendiente")
        params = {"bet_per_line": state["bet_per_line"], "lines": state["lines"]}
        if action in {'spin','buy_spin'}:
            source = profile.get('purchase_value_sources' if action == 'buy_spin' else 'spin_value_sources', {}).get('lines')
            values = settings.get('bet_factor' if source == 'bet_factor_first' else 'lines')
            if source in {'bet_factor_first', 'settings_lines_first'}:
                if not isinstance(values, list) or not values or not isinstance(values[0], (int, float)) or isinstance(values[0], bool) or values[0] < 0 or (values[0] == 0 and source != 'settings_lines_first'):
                    raise ValueError('3 Oaks: origen de líneas de compra pendiente')
                params['lines'] = values[0]
        if not captured_spin and (purchase_params is None or 'bet_factor' in purchase_params):
            if not isinstance(factor, list) or not factor or not isinstance(factor[0], (int,float)) or isinstance(factor[0], bool) or factor[0] <= 0:
                raise ValueError("3 Oaks: perfil de apuesta pendiente")
            params['bet_factor'] = factor[0]
        if action == "buy_spin":
            if selected_mode not in context.get("available_buy_bonus", []):
                raise ValueError("3 Oaks: compra no anunciada")
            mapping = profile.get('purchase_wire_values', {}).get(str(selected_mode), {})
            if purchase_params is None or 'selected_mode' in purchase_params:
                value = mapping.get('selected_mode', selected_mode)
                params['selected_mode'] = str(value) if profile.get('purchase_selector_type') == 'string' else value
            for field in ('buy_spin_scatters_count','ante_bet','paid_feature'):
                if purchase_params and field in purchase_params:
                    if field not in mapping:
                        raise ValueError('3 Oaks: transformación de compra pendiente')
                    params[field] = mapping[field]
        if action == 'spin' and antebet is not None:
            if not profile.get('antebet_executable') or antebet not in profile.get('antebet_values', []):
                raise ValueError('3 Oaks: contrato de antebet pendiente')
            params['ante_bet'] = antebet
    return {"action": {"name": action, "params": params}, "set_denominator": 1,
            "quick_spin": False, "sound": True, "autogame": False,
            "mobile": "0", "portrait": False, "fullscreen": False, "viewportSize": "1280x720"}



def affordable_purchase_fields(data, fields, selected_mode):
    """Choose an advertised stake for the advertised price and current demo balance."""
    import copy
    import math
    result = copy.deepcopy(fields)
    settings = data.get('settings', {})
    params = result.get('action', {}).get('params', {})
    multiplier = settings.get('buy_bonus_prices', {}).get(str(selected_mode))
    balance = data.get('user', {}).get('balance')
    factors = settings.get('bet_factor')
    bets = settings.get('bets')
    def positive(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
    if (not positive(multiplier) or not isinstance(balance, (int, float)) or isinstance(balance, bool)
            or not math.isfinite(balance) or balance < 0 or not isinstance(factors, list) or len(factors) != 1
            or not positive(factors[0]) or not positive(params.get('bet_per_line'))
            or params.get('ante_bet', 0) != 0):
        return result
    unit_cost = multiplier * factors[0]
    if params['bet_per_line'] * unit_cost <= balance:
        return result
    choices = [v for v in bets if positive(v) and v <= params['bet_per_line'] and v * unit_cost <= balance] if isinstance(bets, list) else []
    if not choices:
        raise ValueError('3 Oaks: DEMO_BALANCE_INSUFFICIENT at minimum advertised stake')
    params['bet_per_line'] = max(choices)
    return result

def source_continuation_rules(source: str) -> dict:
    """Certify legacy empty-argument calls from the current fetched client."""
    if ('params:args||{}' not in source
            or not re.search(r'this\.handlers\[action\]\|\|function\(args\)\{return \w+\._act\(action,args\)\}', source)):
        return {}
    rules = {}
    if ('BONUS_INIT:"bonus_init"' in source
            and '.act(_constants.FLOW_ACTIONS.BONUS_INIT)' in source
            and 'setActionHandler(_constants.FLOW_ACTIONS.BONUS_INIT' not in source):
        rules['bonus_init'] = {'current': 'spins'}
    handlers = re.findall(r'setActionHandler\(_constants\.FLOW_ACTIONS\.RESPIN,function\(args\)\{(.{0,1000}?)\}\);', source)
    if ('RESPIN:"respin"' in source and '.act(_constants.FLOW_ACTIONS.RESPIN)' in source and handlers
            and all(re.search(r'return \w+\._act\(_constants\.FLOW_ACTIONS\.RESPIN,args\)', body)
                    and not re.search(r'args\s*=|args\.', body) for body in handlers)):
        rules['respin'] = {'current': 'bonus'}
    if ('.act(_constants.FLOW_ACTIONS.BONUS_STOP)' in source
            and 'setActionHandler(_constants.FLOW_ACTIONS.BONUS_STOP' not in source
            and 'get BONUS_STOP(){return"bonus_".concat(' in source
            and '.model.bonusOriginState(),"_stop")' in source
            and 'this._get("game.bonus.back_to","spins")' in source):
        rules['bonus_spins_stop'] = {'current': 'bonus', 'back_to': 'spins'}
    return rules


def continuation_fields(data: dict, *, game_slug: str, family: str, source_rules=None, client_profile=None) -> dict | None:
    """Only transitions demonstrated by HAR or an active empty-argument serializer."""
    profile = client_profile or {}
    context = data.get('context', {})
    actions = context.get('actions')
    if context.get('round_finished') is not False or not isinstance(actions, list) or len(actions) != 1:
        return None
    action = actions[0]
    rule = (profile or {}).get('continuations', {}).get(action) or (source_rules or {}).get(action)
    if not isinstance(rule, dict) or context.get('current') not in rule.get('currents', [rule.get('current')]):
        return None
    if rule.get('back_to') and context.get('bonus', {}).get('back_to', rule.get('back_to_default')) != rule['back_to']:
        return None
    return play_fields(data, action, game_slug=game_slug, family=family, client_profile=client_profile)


class DemoSession:
    def __init__(self, http, endpoint: str, run_dir, timeout: float, *, browser_fallback=None):
        self.http, self.endpoint, self.run_dir, self.timeout = http, endpoint, run_dir, timeout
        self.session_id = None
        self.browser_fallback = browser_fallback
        self.browser_active = False
        self.index = 0

    def post(self, command: str, fields: dict, *, artifact_dir=None) -> dict:
        body = {"command": command, "request_id": uuid.uuid4().hex,
                "client_command_timestamp": int(time.time() * 1000), **fields}
        if self.session_id:
            body["session_id"] = self.session_id
        label = f"{self.index:03d}-{command}"
        self.index += 1
        directory = artifact_dir if artifact_dir is not None else self.run_dir
        directory.mkdir(parents=True, exist_ok=True)
        # Exact local evidence, never put these session values into reusable exports.
        (directory / (label + ".request.json")).write_text(json.dumps(body, indent=2), encoding="utf-8")
        transport = self.browser_fallback if self.browser_active else self.http
        response = transport.post(self.endpoint, params={"gsc": command},
            data=json.dumps(body, separators=(",", ":")), timeout=self.timeout,
            headers={"Content-Type": "text/plain", "Origin": "https://3oaks.com", "Referer": "https://3oaks.com/"})
        from tester_spin.transport_policy import POLICY
        if (POLICY.may_fallback(dispatched=command != 'login', bootstrap_only=command == 'login', contract_supported=self.browser_fallback is not None)
                and command == 'login' and not self.browser_active and self.browser_fallback is not None
                and getattr(response,'status_code',None) in {403,429}
                and 'Just a moment' in response.text and 'challenge-platform' in response.text):
            (directory / (label + '.response.http-blocked.raw.html')).write_text(response.text,encoding='utf-8')
            self.browser_active = True
            response = self.browser_fallback.post(self.endpoint,params={'gsc':command},
                data=json.dumps(body,separators=(',',':')),timeout=self.timeout,
                headers={'Content-Type':'text/plain'})
        (directory / (label + '.transport.json')).write_text(json.dumps({
            'transport':'browser-fetch' if self.browser_active else 'http'}),encoding='utf-8')
        (directory / (label + ".response.raw.json")).write_text(response.text, encoding="utf-8")
        data = checked_response(response)
        self.session_id = data.get("session_id", self.session_id)
        return data
