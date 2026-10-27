"""Bootstrap and advertised purchases. A source serializer is not execution proof."""
import re
import json
import math

API = "https://rgs-demo.hacksawgaming.com/api"
BONUS_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


def checked_response(response):
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or type(data.get("statusCode")) is not int or data["statusCode"] != 0:
        raise ValueError("Hacksaw: statusCode no exitoso o ausente")
    return data


def terminal(data):
    round_data = data.get("round")
    return (isinstance(round_data, dict) and round_data.get("status") == "completed"
            and round_data.get("possibleActions") == [] and bool(round_data.get("roundId")))


def minimum_round_seconds(raw):
    try:
        value = float(raw or 0)
    except (ValueError, TypeError):
        raise ValueError("Hacksaw: duración mínima inválida")
    if not math.isfinite(value) or value < 0:
        raise ValueError("Hacksaw: duración mínima inválida")
    return value / 1000 if value >= 100 else value


def feature_item_type(bonus):
    """Default get_featureBuyItemType contract in the captured Hacksaw client.

    These are provider protocol prefixes, not lists of games or price thresholds.
    Explicit per-item types take precedence over the default classifier.
    """
    explicit = bonus.get('featureBuyItemType')
    if explicit is not None:
        return explicit
    identifier = str(bonus.get('bonusGameId') or '')
    return ('FeatureSpinItem' if identifier.startswith('mod_') else
            'BestOfBonusItem' if identifier.startswith('bob_') else 'BonusBuyItem')


def _menu_body(source, position=0):
    match = re.compile(r'getFeatureBuyItems:function\([^)]*\)\{').search(source, position)
    if not match:
        return None
    start = match.end(); depth = 1; quote = None; escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == quote: quote = None
        elif char in ('"', "'"): quote = char
        elif char == "`": return None
        elif char == "{": depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0: return source[start:index]
    return None


def client_feature_types(source):
    """Read literal menu items and their explicit type slot without executing JS."""
    registration = re.search(r'\["hacksaw.common.types.FeatureBuyItem"\]=([A-Za-z_$][\w$]*)', source)
    if not registration:
        return {}
    constructor = re.search(r'function '+re.escape(registration[1])+r'\(([^)]*)\)\{([^}]*)\}', source)
    menus=[]
    for menu_match in re.finditer(r'getFeatureBuyItems:function\(',source):
        body=_menu_body(source,menu_match.start())
        if body is None:return {}
        menus.extend(re.findall(r'\breturn\s*\[([^][]*)\]',body))
        for choice in re.finditer(r'\breturn(?:\([^\[\]{};]{1,200}\)|[\w$.!]+)\?\[([^][]*)\]:\[([^][]*)\]',body):
            menus.extend(choice.groups())
    if not constructor or not menus:
        return {}
    params = constructor[1].split(',')
    assignments = re.findall(r'this.featureBuyItemType=([A-Za-z_$][\w$]*)', constructor[2])
    boolean_role=False
    if not assignments:
        assignments=re.findall(r'this.isFeatureSpin=([A-Za-z_$][\w$]*)',constructor[2])
        boolean_role=True
    slots = [params.index(v) for v in assignments if v in params]
    if len(set(slots)) != 1:
        return {}
    slot = slots[0]
    found = {}
    for menu in menus:
        branch = {}
        for call in re.finditer(r'new '+re.escape(registration[1])+r'\(([^()]*)\)', menu):
            args = re.findall(r'"(?:\\.|[^"\\])*"|[^,]+', call[1])
            if len(args) <= slot:
                return {}
            try:
                identifier = json.loads(args[0].strip())
            except (ValueError, TypeError):
                return {}
            if not isinstance(identifier, str) or not BONUS_ID.fullmatch(identifier) or identifier in branch:
                return {}
            raw = args[slot].strip()
            if boolean_role:
                getter=(re.escape(registration[1])+r'\.prototype=\{get_isFeatureSpin:function\(\)\{var (\w+)=this\.isFeatureSpin;return null==\1\?\w+\.startsWith\(this\.bonusGameId,"mod_"\):\1\}')
                if not re.search(getter,source):value='UNRESOLVED_CLIENT_TYPE'
                elif raw in ('true','!0'):value='FeatureSpinItem'
                elif raw in ('false','!1'):value='BonusBuyItem'
                elif raw=='null':
                    getter=(re.escape(registration[1])+r'\.prototype=\{get_isFeatureSpin:function\(\)\{var (\w+)=this\.isFeatureSpin;return null==\1\?\w+\.startsWith\(this\.bonusGameId,"mod_"\):\1\}')
                    value=('FeatureSpinItem' if identifier.startswith('mod_') else 'BonusBuyItem') if re.search(getter,source) else 'UNRESOLVED_CLIENT_TYPE'
                else:value='UNRESOLVED_CLIENT_TYPE'
            elif raw == 'null':
                default = re.search(r'get_featureBuyItemType:function\(\)\{([^}]*)\}', source)
                known_default = (default and
                    re.search(r'\.startsWith\(this\.bonusGameId,"mod_"\)\?"FeatureSpinItem"', default[1]) and
                    re.search(r'\.startsWith\(this\.bonusGameId,"bob_"\)\?"BestOfBonusItem":"BonusBuyItem"', default[1]))
                direct_consumer=(not re.search(r'get_featureBuyItemType\s*:',source) and re.search(
                    r'(\w+)=null!=\1\?\1\.featureBuyItemType:null;[\w$.]+\.featureSpinActive=null!=\1&&"FeatureSpinItem"==\1',source))
                value = (feature_item_type({'bonusGameId':identifier}) if known_default else
                         'BonusBuyItem' if direct_consumer else 'UNRESOLVED_CLIENT_TYPE')
            else:
                try:
                    value = json.loads(raw)
                except (ValueError, TypeError):
                    value = 'UNRESOLVED_CLIENT_TYPE'
            branch[identifier] = value
        for identifier, value in branch.items():
            if identifier in found and found[identifier] != value:
                return {}
            found[identifier] = value
    return found


def discover_modes(data):
    modes = [{"id": "SPIN", "kind": "SPIN", "executable": False, "validated": False,
        "coverage_required": True, "required_options": ["DOMAIN_UNRESOLVED"], "covered_options": [],
        "wire_command": "bet", "reason": "TERMINAL_AND_CONTINUATION_CAPTURE_REQUIRED"}]
    bonuses = data.get("bonusGames", [])
    seen = set()
    if not isinstance(bonuses, list):
        return modes
    for bonus in bonuses:
        if not isinstance(bonus, dict):
            continue
        identifier = bonus.get("bonusGameId")
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int)):
            continue
        if not BONUS_ID.fullmatch(str(identifier)) or str(identifier) in seen:
            continue
        client_types = data.get('client_feature_types')
        item_type = (client_types[str(identifier)] if isinstance(client_types,dict) and str(identifier) in client_types
                     else ('UNRESOLVED_CLIENT_TYPE' if 'client_types_complete' in data and bonus.get('featureBuyItemType') is None
                           else feature_item_type(bonus)))
        kind = {'FeatureSpinItem':'FEATURE_SPIN', 'BonusBuyItem':'PURCHASE',
                'BestOfBonusItem':'PURCHASE'}.get(item_type, 'UNKNOWN_FEATURE') if isinstance(item_type,str) else 'UNKNOWN_FEATURE'
        if kind == 'FEATURE_SPIN' and data.get('disableFeatureSpins') is True:
            continue
        if kind == 'PURCHASE' and data.get('disableBonusBuys') is True:
            continue
        seen.add(str(identifier))
        raw_multiplier = bonus.get("betCostMultiplier")
        multiplier = None
        if not isinstance(raw_multiplier, bool):
            try:
                value = float(raw_multiplier)
                if math.isfinite(value) and value > 0:
                    multiplier = int(value) if value.is_integer() else value
            except (ValueError, TypeError, OverflowError):
                pass
        modes.append({"id": "BUY_" + str(identifier), "kind": kind, "buyBonus": identifier, "feature_item_type": item_type,
            "feature_multiplier": multiplier,
            "wire_command": "bet", "executable": False, "validated": False, "observed": True,
            "evidence_level": "SERVER_ADVERTISED", "coverage_required": True,
            "required_options": [str(identifier)], "covered_options": [],
            "request_shape": {"bets": [{"betAmount": "<dynamic:betAmount>", "buyBonus": identifier}]},
            "reason": "PURCHASE_TERMINAL_AND_CONTINUATION_CAPTURE_REQUIRED"})
    return modes
