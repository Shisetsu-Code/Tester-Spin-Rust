"""BONUS_REQUEST playerChoice -1 keeps current awards; +1 is a risk option.

Recognize the demonstrated DTO family, never a bare Bonus/FreeSpin label.
The same offered free-spin count and the echoed parameters must survive.
"""
import json
from .protocol import command_values
from .named_actions import _board,_number

SOURCE='sdk.BONUS_REQUEST/clientParams.playerChoice/current-award/v1'
ROOT={'GoldenBet','BuyBonus','debug','reelId','initialBoard','finalBoard','freeSpinsAwarded','freeSpinsLeft','win'}
REPLY={'GoldenBet','BuyBonus','freeSpinsAwarded','freeSpinsLeft','GambleAwarded'}
WIN={'wonCash','wonCoins','accumulatedWonCash','accumulatedWonCoins','accumulatedRoundWonCash','accumulatedRoundWonCoins','accumulatedAvalancheWonCash','accumulatedAvalancheWonCoins','prizes'}


BBG_ROOT={'leftMultiplier','rightMultiplier','isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive','gambleAwarded','freeSpinsAwarded','isWinCapped','nextLeftIncrement','nextRightIncrement','version','name','stake','totalStake','currentWinnings','totalWinnings','baseGameWinnings','currentAction','nextActions','finished','reelId','initialGrid','finalGrid','wins'}

def _bbg_offer(cd,commands,constraints=None):
    # Public BBG skipGamble uses the same -1 parameter as BONUS_REQUEST.
    # Identity strings are deliberately not matched; control and award data are.
    if set(cd)!=BBG_ROOT:
        return _bbg_reply(cd,commands,constraints)
    if commands!=['Bonus'] or cd['nextActions']!=commands or cd['finished'] is not False:return None
    if cd['currentAction'] not in ('Spin','Bonus') or cd['reelId']!='BaseGame':return None
    flags=('isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive')
    if any(type(cd[k]) is not bool for k in flags) or sum(cd[k] for k in flags)>1:return None
    if cd['isSuperBuyBonusActive'] or cd['gambleAwarded'] is not False or cd['isWinCapped'] is not False:return None
    if any(type(cd[k]) is not int or cd[k]!=1 for k in ('leftMultiplier','rightMultiplier','nextLeftIncrement','nextRightIncrement')):return None
    if type(cd['freeSpinsAwarded']) is not int or not 1<=cd['freeSpinsAwarded']<=1000:return None
    if any(not _number(cd[k],positive=True) for k in ('stake','totalStake')):return None
    if any(type(cd[k]) not in (int,float) or cd[k]!=0 for k in ('currentWinnings','totalWinnings','baseGameWinnings')) or cd['wins']!=[]:return None
    for key in ('initialGrid','finalGrid'):
        board=cd[key]
        if not isinstance(board,list) or not 1<=len(board)<=20 or not all(isinstance(c,list) and 1<=len(c)<=64 and all(type(v) is int and 0<=v<=65535 for v in c) for c in board):return None
    if cd['initialGrid']!=cd['finalGrid'] or len({len(c) for c in cd['finalGrid']})!=1:return None
    if any(not isinstance(cd[k],str) or not cd[k] for k in ('version','name')):return None
    if commands==['Bonus'] and cd['currentAction']!='Spin' or commands==['FreeSpin'] and cd['currentAction']!='Bonus':return None
    count=cd['freeSpinsAwarded']
    return {'command':commands[0],'free_spins_awarded':count,'free_spins_left':count,'GoldenBet':cd['isGoldenBetActive'],'BuyBonus':cd['isBuyBonusActive'],'clientData':cd,'source':'sdk.BBG.skipGamble/playerChoice/current-award/v1'}

BBG_REPLY=BBG_ROOT-{'reelId','initialGrid','finalGrid','wins'}|{'freeSpinState'}

def _bbg_reply(cd,commands,constraints=None):
    if set(cd)!=BBG_REPLY:return _bbg_cycle(cd,commands,constraints)
    if commands!=['FreeSpin'] or cd['nextActions']!=commands or cd['currentAction']!='Bonus' or cd['finished'] is not False:return None
    if any(cd[k] is not False for k in ('isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive','gambleAwarded','isWinCapped')):return None
    if any(type(cd[k]) is not int or cd[k]!=0 for k in ('leftMultiplier','rightMultiplier','nextLeftIncrement','nextRightIncrement')):return None
    if any(not _number(cd[k],positive=True) for k in ('stake','totalStake')):return None
    if any(type(cd[k]) not in (int,float) or cd[k]!=0 for k in ('currentWinnings','totalWinnings','baseGameWinnings')):return None
    if any(not isinstance(cd[k],str) or not cd[k] for k in ('version','name')):return None
    count=cd['freeSpinsAwarded'];fs=cd['freeSpinState']
    if type(count) is not int or not 1<=count<=1000 or not isinstance(fs,dict) or set(fs)!={'id','spinsRemaining','currentPlay','spinsAwarded','accumulatedWinnings','triggeringDetails'}:return None
    if fs['id']!='FreeSpin' or any(type(fs[k]) is not int or fs[k]!=count for k in ('spinsRemaining','spinsAwarded')) or type(fs['currentPlay']) is not int or fs['currentPlay']!=0 or type(fs['accumulatedWinnings']) not in (int,float) or fs['accumulatedWinnings']!=0:return None
    trigger=fs['triggeringDetails']
    if not isinstance(trigger,dict) or set(trigger) not in ({'view','symbol'},{'view','symbol','offsets'}) or type(trigger['symbol']) is not int or not 0<=trigger['symbol']<=65535:return None
    if 'offsets'in trigger:
        from .bbg_cascades import definition_contract,grid_shape
        contract=definition_contract((constraints or {}).get('bbg_definition'))
        offsets=trigger['offsets']
        if contract is None or grid_shape(trigger['view'])!=contract['shape'] or not isinstance(offsets,list) or not offsets or not all(type(p) is int and p in contract['coordinates'] for p in offsets) or len(set(offsets))!=len(offsets):return None
        if set(offsets)!={p for p,(c,r) in contract['coordinates'].items() if trigger['view'][c][r]==trigger['symbol']}:return None
    board=trigger['view']
    if not isinstance(board,list) or not 1<=len(board)<=20 or not all(isinstance(c,list) and 1<=len(c)<=64 and all(type(v) is int and 0<=v<=65535 for v in c) for c in board) or len({len(c) for c in board})!=1:return None
    return {'command':'FreeSpin','free_spins_awarded':count,'free_spins_left':count,'GoldenBet':False,'BuyBonus':False,'clientData':cd,'source':'sdk.BBG.skipGamble/playerChoice/current-award/v1'}

def _bbg_direct(cd,commands,constraints):
    from .bbg_cascades import definition_contract,cash,grid_shape
    contract=definition_contract((constraints or {}).get('bbg_definition'))
    if contract is None or set(cd)!=BBG_ROOT|{'freeSpinState'} or commands!=['FreeSpin'] or cd['currentAction']!='Spin' or cd['nextActions']!=commands or cd['finished'] is not False:return None
    flags=('isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive')
    if any(type(cd[k]) is not bool for k in flags) or sum(cd[k] for k in flags)>1 or cd['reelId']!=('GoldenBetGame' if cd['isGoldenBetActive'] else 'BaseGame'):return None
    normalized={k:v for k,v in cd.items() if k!='freeSpinState'}
    normalized.update(currentAction='Spin',nextActions=['Bonus'],isSuperBuyBonusActive=False,reelId='BaseGame')
    info=_bbg_offer(normalized,['Bonus'],constraints)
    fs=cd['freeSpinState']
    if info is None or not isinstance(fs,dict) or set(fs)!={'id','spinsRemaining','currentPlay','spinsAwarded','accumulatedWinnings','triggeringDetails'} or fs['id']!='FreeSpin':return None
    count=info['free_spins_awarded']
    if type(fs['currentPlay']) is not int or fs['currentPlay']!=0 or any(type(fs[k]) is not int or fs[k]!=count for k in ('spinsRemaining','spinsAwarded')) or cash(fs['accumulatedWinnings'])!=0:return None
    trigger=fs['triggeringDetails']
    if not isinstance(trigger,dict) or set(trigger)!={'view','symbol','offsets'} or type(trigger['symbol']) is not int or trigger['symbol'] not in contract['symbols'] or grid_shape(trigger['view'])!=contract['shape']:return None
    offsets=trigger['offsets'];coordinates=contract['coordinates']
    if not isinstance(offsets,list) or not offsets or not all(type(p) is int and p in coordinates for p in offsets) or len(set(offsets))!=len(offsets):return None
    if trigger['view']!=cd['initialGrid'] or set(offsets)!={p for p,(c,r) in coordinates.items() if trigger['view'][c][r]==trigger['symbol']}:return None
    return {**info,'command':'FreeSpin','clientData':cd,'source':'sdk.BBG.directAward/FreeSpin/current-award/v1'}

def _bbg_cycle(cd,commands,constraints=None):
    if cd.get('currentAction')=='Spin':return _bbg_direct(cd,commands,constraints)
    if not BBG_ROOT|{'freeSpinState'}<=set(cd)<=BBG_ROOT|{'freeSpinState','cascadeDetails'} or commands not in (['FreeSpin'],['C']) or cd['nextActions']!=(['Spin'] if commands==['C'] else ['FreeSpin']) or cd['currentAction']!='FreeSpin' or cd['reelId']!='FreeGame':return None
    if cd['finished'] is not (commands==['C']):return None
    flags=('isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive')
    if any(type(cd[k]) is not bool for k in flags) or sum(cd[k] for k in flags)>1:return None
    if cd['gambleAwarded'] is not False or cd['isWinCapped'] is not False or type(cd['freeSpinsAwarded']) is not int or cd['freeSpinsAwarded']!=0:return None
    if any(type(cd[k]) is not int or not 1<=cd[k]<=1000000 for k in ('leftMultiplier','rightMultiplier','nextLeftIncrement','nextRightIncrement')):return None
    from .bbg_cascades import cascade_cash,cash
    awarded_cash=cascade_cash(cd,(constraints or {}).get('bbg_definition'))
    if awarded_cash is None or cash(cd['baseGameWinnings'])!=0 or cash(cd['totalWinnings']) is None:return None
    for key in ('initialGrid','finalGrid'):
        board=cd[key]
        if not isinstance(board,list) or not 1<=len(board)<=20 or not all(isinstance(c,list) and 1<=len(c)<=64 and all(type(v) is int and 0<=v<=65535 for v in c) for c in board):return None
    if [len(c) for c in cd['initialGrid']]!=[len(c) for c in cd['finalGrid']] or len({len(c) for c in cd['finalGrid']})!=1:return None
    fs=cd['freeSpinState']
    if not isinstance(fs,dict) or any(type(fs.get(k)) is not int for k in ('spinsAwarded','spinsRemaining','currentPlay')):return None
    previous_cash=cash(fs.get('accumulatedWinnings'))
    if previous_cash is None or cash(cd['totalWinnings'])<previous_cash+awarded_cash:return None
    count=fs['spinsAwarded'];left=fs['spinsRemaining'];played=fs['currentPlay']
    if not 1<=count<=1000 or not 1<=played<=count or left!=count-played or (left==0)!=(commands==['C']):return None
    # Reuse the validated initial free-spin DTO for static stake/trigger fields.
    initial={k:v for k,v in cd.items() if k not in {'reelId','initialGrid','finalGrid','wins','cascadeDetails'}}
    initial.update({k:False for k in flags});initial.update({k:0 for k in ('leftMultiplier','rightMultiplier','nextLeftIncrement','nextRightIncrement')})
    initial.update(currentWinnings=0,totalWinnings=0,baseGameWinnings=0,currentAction='Bonus',nextActions=['FreeSpin'],finished=False,freeSpinsAwarded=count,freeSpinState={**fs,'currentPlay':0,'spinsRemaining':count,'accumulatedWinnings':0})
    info=_bbg_reply(initial,['FreeSpin'],constraints)
    if info is None:return None
    return {**info,'command':commands[0],'free_spins_left':left,'clientData':cd}

def current_info(state,constraints=None):
    if state.get('terminal') or state.get('commands') not in (['Bonus'],['FreeSpin']):return None
    bets=state.get('bets')
    if not isinstance(bets,list) or not bets or not all(isinstance(b,dict) and b.get('status')=='RESULTED' for b in bets):return None
    ed=bets[-1].get('eventdata')
    if not isinstance(ed,dict) or command_values(ed.get('nextCmds'))!=state['commands']:return None
    response=ed.get('response');cd=response.get('clientData') if isinstance(response,dict) else None
    if not isinstance(cd,dict):return None
    if set(cd) not in (ROOT,REPLY):return _bbg_offer(cd,state['commands'],constraints)
    if any(type(cd[k]) is not bool for k in ('GoldenBet','BuyBonus')) or cd['GoldenBet'] and cd['BuyBonus']:return None
    count=cd['freeSpinsAwarded'];left=cd['freeSpinsLeft']
    if type(count) is not int or type(left) is not int or not 1<=left==count<=1000:return None
    if set(cd)==ROOT:
        if cd['debug']!='BG - INITIAL' or cd['reelId'] not in ('BaseReel','BuyBonus') or not _board(cd['initialBoard']) or not _board(cd['finalBoard']) or [len(c)for c in cd['initialBoard']]!=[len(c)for c in cd['finalBoard']]:return None
        win=cd['win']
        if not isinstance(win,dict) or set(win)!=WIN or not all(_number(win[k]) for k in WIN-{'prizes'}) or not isinstance(win['prizes'],list):return None
    elif cd['GambleAwarded']!='False' or state['commands']!=['FreeSpin']:return None
    return {'command':state['commands'][0],'free_spins_awarded':count,'free_spins_left':left,'GoldenBet':cd['GoldenBet'],'BuyBonus':cd['BuyBonus'],'clientData':cd,'source':SOURCE}

def choice_parameters(state,constraints=None):
    info=current_info(state,constraints)
    if info is None:return None
    if info['command']=='Bonus':return {'bonusRound':False,'playerChoice':-1}
    return {} if info['source'].startswith('sdk.BBG.') else {'bonusRound':False}

def validate_parameter_transition(before,after,request,constraints=None):
    from .runtime import Unsupported
    if request.get('cmd') not in ('Bonus','FreeSpin'):return
    expected=choice_parameters(before,constraints)
    try:params=json.loads(request.get('clientParams','{}' if expected=={} else ''))
    except (ValueError,TypeError):raise Unsupported('Malformed parameterized bonus request') from None
    if expected is None or params!=expected or expected!={} and params.get('bonusRound') is not False or request['cmd']=='Bonus' and type(params.get('playerChoice')) is not int:raise Unsupported('Unlearned parameterized bonus request')
    step=int(request['step']);bet=next((b for b in after['bets'] if b['step']==step),None)
    old=current_info(before,constraints)
    if old and old['source'].startswith('sdk.BBG.'):
        from .bbg_cascades import acknowledged_envelope
        prior_bet=before['bets'][-1]
        if not acknowledged_envelope(prior_bet,before['commands']) or bet is None or not acknowledged_envelope(bet,after['commands'],prior_bet['eventdata']['playerState']):raise Unsupported('Unknown or inconsistent BBG continuation envelope')
    echo=(bet.get('betdata')or{}).get('clientParams',{} if expected=={} else None) if bet else None
    if not isinstance(echo,dict) or echo!=expected or expected!={} and echo.get('bonusRound') is not False or request['cmd']=='Bonus' and type(echo.get('playerChoice')) is not int:raise Unsupported('Server did not acknowledge bonus parameters')
    old=current_info(before,constraints)
    if request['cmd']=='FreeSpin' and old and old['source'].startswith('sdk.BBG.'):
        if len([b for b in after['bets'] if b['step']>before['max_step']])!=1:raise Unsupported('Unlearned BBG bulk free-spin response')
        cd=((bet.get('eventdata')or{}).get('response')or{}).get('clientData')
        new=_bbg_cycle(cd,after['commands'],constraints) if isinstance(cd,dict) else None
        previous=old['clientData']['freeSpinState']
        from .bbg_cascades import cash
        if new is not None and (cash(new['clientData']['freeSpinState']['accumulatedWinnings'])!=cash(old['clientData']['freeSpinState']['accumulatedWinnings']) or cash(new['clientData']['totalWinnings'])!=cash(old['clientData']['totalWinnings'])+cash(new['clientData']['currentWinnings']) or cash((bet.get('betdata')or{}).get('accWa'))!=cash(new['clientData']['totalWinnings']) or cash((bet.get('eventdata')or{}).get('accWa'))!=cash(new['clientData']['totalWinnings']) or cash(((bet.get('eventdata')or{}).get('response')or{}).get('cashWin'))!=cash(new['clientData']['currentWinnings'])):raise Unsupported('BBG cascade cash not conserved')
        if new is None or new['free_spins_awarded']!=old['free_spins_awarded'] or new['free_spins_left']!=old['free_spins_left']-1 or new['clientData']['freeSpinState']['currentPlay']!=previous['currentPlay']+1 or any(old['clientData'][k]!=new['clientData'][k] for k in ('stake','totalStake')) or new['clientData']['freeSpinState']['triggeringDetails']!=previous['triggeringDetails']:raise Unsupported('BBG free-spin progression not acknowledged')
    if request['cmd']=='Bonus':
        old=current_info(before,constraints);new=current_info(after,constraints)
        keys=('free_spins_awarded','free_spins_left') if old['source'].startswith('sdk.BBG.') else ('free_spins_awarded','free_spins_left','GoldenBet','BuyBonus')
        if new is None or new['source']!=old['source'] or new['command']!='FreeSpin' or any(old[k]!=new[k] for k in keys):raise Unsupported('Refusal did not preserve the currently offered free spins')
        if old['source'].startswith('sdk.BBG.') and any(old['clientData'][k]!=new['clientData'][k] for k in ('stake','totalStake')):raise Unsupported('Refusal changed the award stake')
