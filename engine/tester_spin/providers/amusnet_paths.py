"""Observed complex-slot feature and gamble paths; no inferred paid absence."""
from fractions import Fraction
from tester_spin.providers.amusnet import integer


def feature_bet(initial,name,base):
    settings=initial.get('settings',{}).get('gameSettings',{}).get('complex',{})
    ids=settings.get('featureIds',{});prices=settings.get('featureMultipliers',{})
    if name not in {'NONE','BUY_FREESPINS','DOUBLE_CHANCE'} or name not in ids:
        raise ValueError('FEATURE_DOMAIN_UNBOUND')
    identity=ids[name]
    if type(identity) is not int or type(base) is not int or base not in settings.get('bets',[]):
        raise ValueError('FEATURE_BASE_QUOTE_UNBOUND')
    try:multiplier=Fraction(str(prices[str(identity)]))
    except (KeyError,ValueError,ZeroDivisionError):raise ValueError('FEATURE_PRICE_UNBOUND')
    cost=base*multiplier
    if multiplier<=0 or cost.denominator!=1:raise ValueError('FEATURE_PRICE_UNBOUND')
    return {'bet':int(cost),'betMultiplier':float(multiplier) if multiplier.denominator!=1 else int(multiplier),
            'bonus':False,'featureId':identity,'gameCommand':'bet'}


def _verify_path(initial,pairs,*,gin,require_terminal):
    if (not pairs or initial.get('currency')!='FUN' or initial.get('status')!='success'
            or initial.get('gameMetadata',{}).get('gin')!=gin
            or initial.get('states',{}).get('gameState',{}).get('complex',{}).get('currentState',{}).get('state')!='idle'):
        raise ValueError('FUN_IDLE_PATH_REQUIRED')
    first=pairs[0]['request'].get('bet',{})
    ids=initial.get('settings',{}).get('gameSettings',{}).get('complex',{}).get('featureIds',{})
    names=[name for name,value in ids.items() if value==first.get('featureId')]
    if len(names)!=1:raise ValueError('FEATURE_ID_UNBOUND')
    try:base=Fraction(str(first['bet']))/Fraction(str(first['betMultiplier']))
    except (KeyError,ValueError,ZeroDivisionError):raise ValueError('FEATURE_PRICE_UNBOUND')
    if base.denominator!=1 or first!=feature_bet(initial,names[0],int(base)):
        raise ValueError('FEATURE_REQUEST_MISMATCH')
    before=integer(initial.get('balance'));cost=integer(first['bet']);round_id=None
    previous=None;win=0;choices=[]
    for index,pair in enumerate(pairs):
        req=pair['request'];res=pair['response'];bet=req.get('bet',{})
        if (req.get('command')!='bet' or req.get('gin')!=gin or res.get('command')!='bet'
                or res.get('msg')!='success' or req.get('messageId')!=res.get('messageId')):
            raise ValueError('PATH_RESPONSE_CORRELATION_UNBOUND')
        if index==0:
            if res.get('gin')!=gin or not str(res.get('gameNumber','')).isdigit():raise ValueError('PATH_ROUND_UNBOUND')
            round_id=res['gameNumber']
        else:
            if req.get('gameNumber')!=round_id:raise ValueError('PATH_ROUND_MISMATCH')
            if previous=='freespin':
                if bet!={**first,'bonus':True} or req.get('bonusData') is not None:raise ValueError('BONUS_CONTINUATION_MISMATCH')
            elif previous=='gamble':
                if bet=={'gameCommand':'collect'}:pass
                elif bet.get('gameCommand')=='gamble' and type(bet.get('color')) is int and bet['color'] in (0,1) and set(bet)=={'color','gameCommand'}:
                    choices.append(bet['color'])
                else:raise ValueError('GAMBLE_CHOICE_UNBOUND')
            else:raise ValueError('ACTION_AFTER_TERMINAL')
        if res.get('gameNumber')!=round_id or res.get('gin') not in (gin,0):raise ValueError('PATH_ROUND_MISMATCH')
        state=res.get('state');new_win=integer(res.get('winAmount'))
        if index and previous=='gamble' and bet.get('gameCommand')=='gamble' and new_win not in (0,win*2):
            raise ValueError('GAMBLE_LEDGER_MISMATCH')
        if index and bet.get('gameCommand')=='collect' and new_win!=win:raise ValueError('COLLECT_WIN_MISMATCH')
        if state not in ('idle','freespin','gamble'):raise ValueError('UNKNOWN_PATH_STATE')
        if res.get('complex',{}).get('gameCommand')!=bet.get('gameCommand'):raise ValueError('PATH_COMMAND_MISMATCH')
        if 'balance' in res:
            expected=before-cost+(new_win if state=='idle' else 0)
            if integer(res['balance'])!=expected:raise ValueError('PATH_LEDGER_MISMATCH')
        win=new_win;previous=state
    final=pairs[-1]['response']
    if (require_terminal or previous=='idle') and (previous!='idle' or 'balance' not in final
            or final.get('pendingWinResult',{}).get('totalRemainingOverflowAmount')!=0):
        raise ValueError('PATH_NOT_TERMINAL')
    return {'schema':'tester-spin/amusnet-feature-settlement/v1','state':'CLOSED' if previous=='idle' else 'OPEN',
            'mode':names[0],'gin':gin,'round_id':round_id,'base_bet':int(base),'cost':cost,
            'balance_before':before,'balance_after':final.get('balance'),'win':win,
            'wire_steps':len(pairs),'gamble_choices':choices,'paid_inventory_complete':False}


def verify_path(initial,pairs,*,gin):
    return _verify_path(initial,pairs,gin=gin,require_terminal=True)


def execute_path(initial,name,base,*,gin,previous_round,exchange,save,max_steps=100,stop_event=None):
    """Execute only the observed feature continuations; never retry a dispatch.

    The injected transport owns correlation IDs and timeouts. Every response is
    validated before another command. A freespin counter reaching zero is not
    terminal: the server state, overflow and reconciled final balance must close.
    Unknown choices stay blocked; an observed gamble state uses collect only.
    """
    first=feature_bet(initial,name,base)
    if (initial.get('currency')!='FUN' or initial.get('status')!='success'
            or initial.get('gameMetadata',{}).get('gin')!=gin
            or initial.get('states',{}).get('gameState',{}).get('complex',{}).get('currentState',{}).get('state')!='idle'):
        raise ValueError('FUN_IDLE_PATH_REQUIRED')
    if type(max_steps) is not int or max_steps<1:raise ValueError('INVALID_PATH_STEP_LIMIT')
    if not isinstance(previous_round,str) or (previous_round!='-1' and not previous_round.isdigit()):
        raise ValueError('PATH_PREVIOUS_ROUND_UNBOUND')
    if integer(initial.get('balance'))<first['bet']:raise ValueError('INSUFFICIENT_FUN_BALANCE')
    fields={'bet':dict(first),'gameNumber':previous_round,'bonusData':None};pairs=[]
    for index in range(max_steps):
        if stop_event is not None and stop_event.is_set():raise ValueError('STOP_REQUESTED_UNSETTLED_PATH')
        save(f'dispatch-{index+1:03d}.json',{'state':'DISPATCHED_UNCERTAIN_UNTIL_SETTLED','fields':fields})
        request,response=exchange('bet',fields)
        pair={'request':request,'response':response};pairs.append(pair)
        save(f'wire-{index+1:03d}.json',pair)
        if any(request.get(key)!=value for key,value in fields.items()):raise ValueError('PATH_DISPATCH_BINDING_MISMATCH')
        receipt=_verify_path(initial,pairs,gin=gin,require_terminal=False)
        if receipt['state']=='CLOSED':
            save('settlement.json',receipt)
            return pairs,receipt
        if response['state']=='freespin':
            fields={'bet':{**first,'bonus':True},'gameNumber':response['gameNumber'],'bonusData':None}
        elif response['state']=='gamble':
            fields={'bet':{'gameCommand':'collect'},'gameNumber':response['gameNumber']}
        else:raise ValueError('UNKNOWN_PATH_STATE')
    raise ValueError('PATH_STEP_LIMIT_UNCERTAIN')
