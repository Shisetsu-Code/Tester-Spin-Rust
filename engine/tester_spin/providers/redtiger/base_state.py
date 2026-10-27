"""Red Tiger base-state evidence, independent of catalog names and identifiers."""
import re

from .result_tree import result_nodes, walk_tree


def classify_base_state(payload, *, request=None, previous=None):
    def verdict(base, reason, **signals):
        return {'base':base, 'known':base, 'reason':reason, 'signals':signals}
    if not isinstance(payload, dict) or payload.get('success') is not True:
        return verdict(False, 'unsuccessful_response')
    result=payload.get('result')
    game=result.get('game') if isinstance(result, dict) else None
    if not isinstance(game, dict):
        return verdict(False, 'missing_game_result')
    nodes=result_nodes(game)
    if not nodes:
        return verdict(False, 'missing_outcome_evidence')
    marker=game.get('mode')
    if (isinstance(marker,dict) and set(marker)=={'active'} and marker['active'] is False
            and _independent_settled_paid_round(payload,request,previous)):
        projected_game=dict(game);projected_game.pop('mode')
        projected={**payload,'result':{**result,'game':projected_game}}
        proof=classify_base_state(projected,request=request,previous=previous)
        if proof['base']:
            return verdict(True,'independent_settled_round_with_inactive_mode_marker',
                stake_debited=True,winnings_settled=True,round_advanced=True)
    # Inline Respin frames may be settled outcome history, not another round.
    # Only an explicitly closed paid Normal root with linked ledger/round IDs
    # can supply the closure proof when frames omit their own isLast flags.
    from .runtime import choice_state
    nsp = game.get('nsp')
    if (set(game)=={'win','nsp','hasState'} and type(game.get('hasState')) is bool
            and isinstance(nsp,dict) and isinstance(nsp.get('reels'),list) and nsp['reels']
            and set(nsp)<={'stake','reels','multiWays','multiplier','winMul','winning','spinning','state'}
            and _empty_state_containers(nsp.get('state'))
            and _independent_settled_paid_round(payload,request,previous)
            and _choice_round_components_normal(game,empty_state_containers=True)):
        return verdict(True,'independent_settled_nsp_round_with_empty_state_containers',
                       has_state=game['hasState'],stake_debited=True,winnings_settled=True,round_advanced=True)
    if (game.get('spinMode') == 'Normal' and type(game.get('gameMode')) is int
            and game['gameMode'] == 0 and type(game.get('hasState')) is bool
            and game.get('features') == [] and isinstance(game.get('respin'), list)
            and game['respin'] and choice_state(payload)['status'] in {'NONE','RESOLVED'}
            and _independent_settled_paid_round(payload, request, previous)
            and _choice_round_components_normal(game, settled_root=True)):
        return verdict(True, 'independent_settled_normal_round_with_inline_outcomes',
                       has_state=game['hasState'], stake_debited=True, winnings_settled=True,
                       round_advanced=True)
    # Success and a normal request do not override a returned bonus/choice.
    for path, value in walk_tree(game):
        if not isinstance(value, dict):
            continue
        choices=value.get('choices')
        if isinstance(choices, dict) and choices.get('available') and not choices.get('selected'):
            return verdict(False, 'pending_choice', path=path)
        if value.get('mandatoryFeature') is True:
            return verdict(False, 'mandatory_feature_pending', path=path)
        if any(value.get(k) for k in ('fsp','rsp','features')):
            return verdict(False, 'feature_or_continuation_present', path=path)
        if 'state' in value and value['state'] not in (None, [], {}):
            return verdict(False, 'uninterpreted_state', path=path)
        if 'mode' in value and str(value['mode']).lower() != 'normal':
            return verdict(False, 'non_normal_component', path=path)
    for node in nodes:
        if node.spin_mode and node.spin_mode.lower() != 'normal':
            return verdict(False, 'non_normal_spin_mode', path=node.path, spin_mode=node.spin_mode)
        if node.game_mode is not None and (type(node.game_mode) is not int or node.game_mode != 0):
            return verdict(False, 'non_normal_game_mode', path=node.path, game_mode=node.game_mode)
    normal=bool(game.get('spinMode') and str(game['spinMode']).lower()=='normal') or type(game.get('gameMode')) is int and game['gameMode']==0
    if all(node.has_state is False for node in nodes) and normal:
        return verdict(True, 'closed_normal_result', has_state=False)
    nsp=game.get('nsp')
    if (all(node.has_state is False for node in nodes) and game.get('state')==[]
            and isinstance(nsp,dict) and isinstance(nsp.get('reels'),list) and nsp['reels']):
        return verdict(True, 'closed_normal_spin_outcome', has_state=False, outcome='nsp', state=[])
    if (normal and game.get('debugNormal') is True and game.get('features')==[]
            and isinstance(game.get('reelsBuffer'),list) and game['reelsBuffer']
            and len(nodes)==1):
        return verdict(True, 'explicit_normal_outcome_with_persistent_state',
                       has_state=game.get('hasState'), debug_normal=True)
    if (normal and (game.get('spinMode') == 'Normal'
                        or ('spinMode' not in game and ('mandatoryFeature' not in game or game.get('mandatoryFeature') is False)))
            and game.get('gameMode') == 0
            and game.get('hasState') is True and game.get('features') == []
            and isinstance(game.get('reelsBuffer'), list) and game['reelsBuffer']
            and len(nodes) == 1 and _independent_settled_paid_round(payload, request, previous)):
        return verdict(True, 'independent_settled_normal_round_with_persistent_state',
                       has_state=True, stake_debited=True, winnings_settled=True,
                       round_advanced=True)
    nsp = game.get('nsp')
    if (set(game) == {'win', 'nsp', 'hasState'} and type(game.get('hasState')) is bool
            and isinstance(nsp, dict) and isinstance(nsp.get('reels'), list) and nsp['reels']
            and len(nodes) == 1
            and _independent_settled_paid_round(payload, request, previous)):
        return verdict(True, 'independent_settled_nsp_round_with_persistent_state',
                       has_state=game['hasState'], stake_debited=True, winnings_settled=True, round_advanced=True)
    return verdict(False, 'insufficient_base_evidence',
                   has_state=game.get('hasState'), normal_mode=normal,
                   note='hasState alone does not identify a bonus or prove base state')


def _independent_settled_paid_round(payload, request, previous):
    """Financial/round evidence distinguishes persisted state from continuation."""
    from decimal import Decimal, InvalidOperation
    def money(value):
        if isinstance(value, bool):
            return None
        try:
            number = Decimal(str(value))
            return number if number.is_finite() else None
        except (InvalidOperation, TypeError, ValueError):
            return None
    if not isinstance(request, dict) or not isinstance(previous, dict) or previous.get('success') is not True:
        return False
    if request.get('extras') not in (None, {}) or request.get('bonusId') is not None or type(request.get('gameMode')) is not int or request['gameMode'] != 0:
        return False
    try:
        result, before = payload['result'], previous['result']
        round_id, previous_id = result['transactions']['roundId'], before['transactions']['roundId']
        if type(round_id) is not int or type(previous_id) is not int or previous_id <= 0 or round_id <= previous_id:
            return False
        stake = money(request.get('stake'))
        game = result['game']
        game_stake = money(game.get('stake'))
        if set(game) == {'win', 'nsp', 'hasState'}:
            game_stake = money(game['win'].get('stake'))
            nsp=game['nsp']
            if 'stake' in nsp:
                if game_stake != money(nsp['stake']):return False
            elif not _closed_unstaked_nsp(nsp,game['win'],money):
                return False
        win = money(result['game']['win'].get('total'))
        balance = result['user']['balance']['cash']
        start, after_bet, end = [money(balance.get(k)) for k in ('atStart', 'afterBet', 'atEnd')]
        previous_end = money(before['user']['balance']['cash'].get('atEnd'))
        if any(v is None for v in (stake, game_stake, win, start, after_bet, end, previous_end)):
            return False
        return (stake > 0 and game_stake == stake and win >= 0 and start == previous_end
                and start - after_bet == stake and end - after_bet == win)
    except (KeyError, TypeError, AttributeError):
        return False


def _closed_unstaked_nsp(nsp,win,money):
    """Closed NSP payout presentation whose stake is explicitly in game.win."""
    required={'reels','winMul','lines','winning'}
    allowed=required|{'spinning','randomWildOverlay','randomWildCount','lockedWildOverlay','lockedWildCount'}
    if not isinstance(nsp,dict) or not required<=set(nsp) or set(nsp)-allowed:return False
    if not isinstance(nsp['reels'],list) or not nsp['reels'] or any(not isinstance(v,str) or not v for v in nsp['reels']):return False
    total,stake,total_multiplier=money(win.get('total')),money(win.get('stake')),money(win.get('winMul'))
    line_multiplier=money(nsp['winMul'])
    if any(v is None for v in (total,stake,total_multiplier,line_multiplier)):return False
    if total<0 or stake<=0 or total_multiplier<0 or line_multiplier<0:return False
    if money(nsp['winning'])!=total or total_multiplier*stake!=total:return False
    # Line multipliers and the whole-stake multiplier have different units.
    # Match each only to its own evidence, without guessing a line stake.
    lines=nsp['lines']
    if not isinstance(lines,list) or len(lines)>512:return False
    line_total=money(0)
    line_keys={'winMul','cells','hit','symbol','winCount'}
    for line in lines:
        if not isinstance(line,dict) or not line_keys<=set(line) or set(line)-line_keys-{'winStart'}:return False
        multiplier=money(line['winMul']);cells=line['cells'];hit=line['hit'];symbol=line['symbol'];count=line['winCount']
        if multiplier is None or multiplier<=0:return False
        if not isinstance(cells,str) or not re.fullmatch(r'[0-9]{1,64}',cells):return False
        if not isinstance(hit,str) or len(hit)!=len(cells):return False
        if not isinstance(symbol,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}',symbol):return False
        if type(count) is not int or not 1<=count<=len(hit):return False
        start=line.get('winStart',0)
        if type(start) is not int or start<0 or start+count>len(hit):return False
        line_total+=multiplier
    if line_total!=line_multiplier:return False
    for key in ('randomWildOverlay','lockedWildOverlay'):
        if key in nsp and nsp[key]!=[]:return False
    for key in ('randomWildCount','lockedWildCount'):
        if key in nsp and (type(nsp[key]) is not int or nsp[key]!=0):return False
    spinning=nsp.get('spinning',{})
    if not isinstance(spinning,dict) or set(spinning)-{'spins','speeds','nearMiss'}:return False
    if 'nearMiss' in spinning and type(spinning['nearMiss']) is not bool:return False
    for key in ('spins','speeds'):
        if key not in spinning:continue
        values=spinning[key]
        if not isinstance(values,list) or not values or any(money(v) is None or money(v)<0 for v in values):return False
        if key=='spins' and any(money(v)!=0 for v in values):return False
    return True


def settled_paid_choice_round(request, entry, steps, previous=None):
    """An ordinary paid round can close via a sequence of zero-cost choices."""
    from .runtime import _decimal, choice_state, choice_reply_warnings, pending_choice_from_response
    try:
        if entry.get('success') is not True or not steps:
            return False
        game = entry['result']['game']
        if not _choice_round_components_normal(game):
            return False
        if game.get('spinMode') != 'Normal' or type(game.get('gameMode')) is not int or game['gameMode'] != 0 or game.get('features') != []:
            return False
        if request.get('extras') not in (None, {}) or request.get('bonusId') is not None or type(request.get('gameMode')) is not int or request['gameMode'] != 0:
            return False
        stake = _decimal(request.get('stake'))
        cash = entry['result']['user']['balance']['cash']
        start, after, end = [_decimal(cash[k]) for k in ('atStart','afterBet','atEnd')]
        win = _decimal(game['win']['total'])
        round_id = entry['result']['transactions']['roundId']
        if type(round_id) is not int or round_id <= 0 or any(v is None for v in (stake,start,after,end,win)) or stake <= 0 or _decimal(game.get('stake')) != stake:
            return False
        if start - after != stake or win < 0 or end - after != win:
            return False
        if previous is not None:
            old_id = previous['result']['transactions']['roundId']
            if type(old_id) is not int or old_id <= 0 or round_id <= old_id or start != _decimal(previous['result']['user']['balance']['cash']['atEnd']):
                return False
        before = entry
        for command, response in steps:
            prompt = pending_choice_from_response(before)
            selected = command.get('choice')
            if prompt is None or selected not in prompt.available or (type(command.get('roundId')) is not int or command.get('roundId') != round_id) or response.get('success') is not True or choice_reply_warnings(prompt, selected, response):
                return False
            if not _choice_round_components_normal(response['result']['game']):
                return False
            cash = response['result']['user']['balance']['cash']
            a,b,c = [_decimal(cash[k]) for k in ('atStart','afterBet','atEnd')]
            paid = _decimal(response['result']['game']['win']['total'])
            if any(v is None for v in (a,b,c,paid)) or a != end or a != b or paid < 0 or c-b != paid:
                return False
            end, before = c, response
        final = before['result']['game']
        if choice_state(before)['status'] != 'RESOLVED' or final.get('hasState') is not False or (type(final.get('gameMode')) is not int or final.get('gameMode') != 0) or final.get('features') != [] or (final.get('gameData') or {}).get('spinMode') != 'Normal':
            return False
        for _, value in walk_tree(final):
            if isinstance(value,dict) and (any(value.get(k) for k in ('fsp','rsp','features')) or value.get('mandatoryFeature') is True):
                return False
            if isinstance(value,dict):
                choices=value.get('choices')
                if isinstance(choices,dict) and choices.get('available') and not choices.get('selected'):
                    return False
                if 'state' in value and value['state'] not in (None, [], {}):
                    return False
                if value.get('spinMode') not in (None, 'Normal'):
                    return False
        return True
    except (KeyError, TypeError, AttributeError):
        return False


def _empty_state_containers(value, depth=0):
    if depth>16:return False
    if value is None:return True
    if isinstance(value,(dict,list)) and len(value)<=128:
        return all(_empty_state_containers(v,depth+1) for v in (value.values() if isinstance(value,dict) else value))
    return False


def _choice_round_components_normal(game, *, settled_root=False,empty_state_containers=False):
    from .runtime import _decimal
    completed = []
    for path, value in walk_tree(game):
        if not isinstance(value, dict) or 'respin' not in value:
            continue
        frames = value['respin']
        if not isinstance(frames, list):
            if path.endswith(('.win', '.winsMultipliers')) and _decimal(frames) is not None:
                continue
            return False
        if not frames:
            return False
        for index, frame in enumerate(frames):
            if (not isinstance(frame, dict) or frame.get('spinMode') != 'Respin'
                    or not (frame.get('hasState') is None or frame.get('hasState') is False)
                    or not isinstance(frame.get('reelsBuffer'), list) or not frame['reelsBuffer']
                    or _decimal((frame.get('win') or {}).get('total')) is None
                    or ('isLast' in frame and frame['isLast'] is not (index == len(frames)-1))
                    or ('isLast' not in frame and not settled_root)):
                return False
        completed.append(path + '.respin[')
    for path, value in walk_tree(game):
        if not isinstance(value, dict):
            continue
        inline = any(path.startswith(prefix) for prefix in completed)
        if 'gameMode' in value and (type(value['gameMode']) is not int or value['gameMode'] != 0):
            return False
        if settled_root and 'hasState' in value and value['hasState'] is not None and type(value['hasState']) is not bool:
            return False
        if path != '$' and value.get('hasState') is True:
            return False
        if any(value.get(k) for k in ('fsp','rsp','bonus')) or value.get('mandatoryFeature') is True:
            return False
        if value.get('features') and not inline:
            return False
        if inline and value.get('hasState') is True:
            return False
        if ('state' in value and value['state'] not in (None, [], {})
                and not (empty_state_containers and _empty_state_containers(value['state']))):
            return False
        if value.get('spinMode') not in ((None, 'Normal', 'Respin') if inline else (None, 'Normal')):
            return False
        if 'mode' in value and str(value['mode']).lower() != 'normal':
            return False
        choices = value.get('choices')
        if choices is not None and path != '$':
            if isinstance(choices,list) and isinstance(value.get('options'),list):
                from .runtime import resolved_pickers
                records=resolved_pickers({'result':{'game':{'picker':value}}})
                if not records or records[0]['status']!='RESOLVED':return False
            elif (not isinstance(choices,dict) or set(choices)!={'selected','available'}
                  or not isinstance(choices.get('selected'),str) or not choices['selected'].strip()
                  or choices.get('available') not in (None,[])):
                return False
    return True
