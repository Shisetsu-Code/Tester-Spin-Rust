"""Source-certified simple bonus picks; no null-init or custom-pick guessing."""
from __future__ import annotations
import hashlib
import re
from typing import Any


_SCHEMA = 'pragmatic/simple-bonus-pick/v1'
_MAX_ITEMS = 128


def _method(source: str, owner: str, name: str) -> str | None:
    match = re.search(re.escape(owner) + r'\.prototype\.' + re.escape(name) + r'=function\([^)]*\)\{', source)
    if not match:
        return None
    depth, quote, escaped = 1, '', False
    for index in range(match.end(), min(len(source), match.end() + 24000)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = ''
        elif char in ('"', "'"):
            quote = char
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[match.end():index]
    return None


def certify_bonus_contract(js_text: str, source_url: str = '') -> dict[str, Any] | None:
    source = re.sub(r'\s+', '', js_text)
    dictionary = re.search(r'BonusGame:\{status:(.{0,1500}?)bonusGameChoice:["\']([^"\']+)["\']', source)
    send = _method(source, 'GameConnection', 'SendBonusRequest')
    pick = _method(source, 'BonusPickConnection', 'SendItemPick')
    status = _method(source, 'BonusPickConnection', 'ItemsStatus')
    activate = _method(source, 'BonusGameMultiplePicks', 'ActivatePicks')
    bridge = _method(source, 'VideoSlotsConnectionXTLayer', 'OnBonusPick')
    if not all((dictionary, send, pick, status, activate, bridge)):
        return None
    tests = (
        'functionVsBonusGamePlayerChoice(index){this.Index=index;this.PickType=0}' in source,
        'data.Fields[GameProtocolDictionary.Actions.action]=GameProtocolDictionary.Actions.doBonus' in send,
        'if(param.PickType==0)data.Fields[GameProtocolDictionary.BonusGame.bonusGameChoice]=Number(param.Index).toString()' in send,
        'newVsBonusGamePlayerChoice(itemId)' in pick,
        'EventManager.Trigger(GameEvents.evtBonusPickRequest+this.xtLayer.gameSymbol,option)' in pick,
        'returnthis.lastResponse.BonusTable.Status' in status,
        'result.BonusTable.Status=GameProtocolCommonParser.ParseIntList(nameValues,GameProtocolDictionary.BonusGame.status)' in source,
        'result.initialized=nameValues[GameProtocolDictionary.BonusGame.realWin]!=undefined' in source,
        'this.pickItems[itemIndex].ActivateInput(bonusData.ItemsStatus[itemIndex]<=0)' in activate,
        'itemIndex>=bonusData.ItemsStatus.length' in activate,
        'var i=XT.GetInt(Vars.BonusPickItemIndex)'.replace(' ', '') in bridge,
        'this.bonusConnection.SendItemPick(i)' in bridge,
    )
    if not all(tests):
        return None
    fields = dictionary.group(0)
    def key(name: str) -> str | None:
        match = re.search(r'\b' + name + r':["\']([^"\']+)["\']', fields)
        return match.group(1) if match else None
    status_key, initialized_key = key('status'), key('realWin')
    if not status_key or not initialized_key:
        return None
    return {
        'schema': _SCHEMA, 'wire_action': 'doBonus',
        'wire_field': dictionary.group(2), 'status_key': status_key,
        'initialized_key': initialized_key, 'source_url': source_url,
        'source_sha256': hashlib.sha256(js_text.encode('utf-8')).hexdigest(),
        'domain_basis': 'BonusGameMultiplePicks enables zero-based items whose server status is <= 0',
        'evidence': {'dictionary': fields, 'send': send, 'pick': pick, 'status': status,
                     'activate': activate, 'bridge': bridge},
    }


def discover_bonus_contract(session: Any, source_url: str, timeout_s: float = 20.0) -> dict[str, Any] | None:
    """Read an already observed official build URL (e.g. reel contract source_url)."""
    response = session.get(source_url, timeout=timeout_s)
    response.raise_for_status()
    if len(response.content) > 12 * 1024 * 1024:
        raise ValueError('Official bonus source exceeds size bound')
    return certify_bonus_contract(response.text, str(response.url))


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not re.fullmatch(r'-?[0-9]+', str(value)):
        raise ValueError(f'Invalid bonus {field}: expected integer')
    return int(value)


def bonus_selection(response: dict[str, Any], contract: dict[str, Any] | None,
                    override: int | str | None = None) -> dict[str, Any] | None:
    """Choose an available simple-pick index, with explicit test-policy metadata.

    None means this is not an initialized certified pick. It does not authorize
    sending a no-index doBonus: that separate init path must be proven by caller.
    The client has no automatic default; absent override uses the first available
    option as a deterministic testing policy, without implying full coverage.
    """
    if response.get('na') != 'b' or str(response.get('end', '')) != '0' or contract is None:
        return None
    if contract.get('schema') != _SCHEMA:
        raise ValueError('Uncertified simple bonus contract')
    if contract['initialized_key'] not in response and contract['status_key'] not in response:
        return None
    raw_status = response.get(contract['status_key'])
    if raw_status is None:
        raise ValueError('Initialized bonus has no item status table')
    entries = str(raw_status).split(',')
    if not 1 <= len(entries) <= _MAX_ITEMS:
        raise ValueError('Bonus item table exceeds supported bound')
    statuses = [_integer(value, 'item status') for value in entries]
    for key in ('wins', 'wins_mask'):
        if key in response and len(str(response[key]).split(',')) != len(statuses):
            raise ValueError('Bonus item table lengths disagree')
    domain = [str(index) for index, value in enumerate(statuses) if value <= 0]
    if not domain:
        raise ValueError('Active bonus has no selectable item')
    selected = domain[0] if override is None else str(_integer(override, 'override'))
    if selected not in domain:
        raise ValueError('Bonus selection is unavailable or outside the server table')
    bonus_type = _integer(response.get('bgt'), 'type')
    level = _integer(response.get('level'), 'level')
    return {
        'fields': {contract['wire_field']: selected},
        'selected': selected, 'default': None, 'domain': domain,
        'selection_policy': 'first_available_test_choice' if override is None else 'explicit_override',
        'branch_signature': f"PRAGMATIC:bonus-pick:bgt={bonus_type}:level={level}:status={','.join(map(str,statuses))}",
        'coverage_branch_signature':f'PRAGMATIC:bonus-pick:bgt={bonus_type}:size={len(statuses)}:level={level}',
        'domain_basis': contract['domain_basis'],
        'contract_source': contract['source_url'], 'contract_sha256': contract['source_sha256'],
    }
