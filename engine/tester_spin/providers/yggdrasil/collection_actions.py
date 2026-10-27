"""Current stake-bound collection display; awarded features remain unknown."""
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from .named_actions import _number,ordinary_named_actions
from .protocol import command_values

def collection_envelope(event):
    if not isinstance(event,dict):return False
    if any(isinstance(event.get(k),dict) and 'collectionsMap' in event[k] for k in ('playerState','initialPlayerState')):return True
    boost=event.get('boostData')
    if isinstance(boost,dict) and {'collections','multiplierIncreasedTo5','freeSpinsEntered'} & set(boost):return True
    return {'boostData','initialPlayerState','playerState'}<=set(event) and (not isinstance(boost,dict) or any(not isinstance(event[k],dict) for k in ('initialPlayerState','playerState')))


def _resolved_collection(action,symbols,coin,multiplier):
    if set(action)!={'name','type','wins'} or not isinstance(action['wins'],list) or not 1<=len(action['wins'])<=256:return None
    result=deepcopy(action);result['type']='regular'
    for win in result['wins']:
        if not isinstance(win,dict) or set(win)!={'value','multiplier','initialValue','positions','symbol','oak','collectors','beforeMultiplier'} or win['symbol']!='CASH' or not _number(win['multiplier'],positive=True) or Decimal(str(win['multiplier']))!=multiplier:return None
        money=[]
        for key in ('value','initialValue','beforeMultiplier'):
            value=win[key]
            if not isinstance(value,dict) or set(value)!={'cash','coins'} or not all(_number(v) for v in value.values()):return None
            amounts={k:Decimal(str(v)) for k,v in value.items()}
            if amounts['cash']!=amounts['coins']*coin:return None
            money.append(amounts)
        if money[1]!=money[2] or any(money[0][k]!=money[2][k]*multiplier for k in money[0]):return None
        groups=[]
        for key,kind in [('positions','CASH'),('collectors','COLLECT')]:
            positions=win[key]
            if not isinstance(positions,list) or not positions or len(positions)>256:return None
            coords=[]
            for pos in positions:
                if not isinstance(pos,dict) or set(pos)!={'column','row'} or any(type(v) is not int for v in pos.values()):return None
                coord=(pos['column'],pos['row']);symbol=symbols.get(coord)
                if not isinstance(symbol,dict) or symbol.get('name')!=kind:return None
                if kind=='CASH':
                    amount=symbol.get('value')
                    if not isinstance(amount,dict) or set(amount)!={'cash','coins'} or not all(_number(v) for v in amount.values()):return None
                coords.append(coord)
            if len(set(coords))!=len(coords):return None
            groups.append(coords)
        for key in ('cash','coins'):
            if sum((Decimal(str(symbols[pos]['value'][key])) for pos in groups[0]),Decimal(0))!=money[2][key]:return None
        win.pop('collectors');win.pop('beforeMultiplier')
    return result

def ordinary_collection_actions(bet,constraints=None):
    if not isinstance(bet,dict):return False
    ed=bet.get('eventdata');bd=bet.get('betdata')
    if not isinstance(ed,dict) or not isinstance(bd,dict) or bd.get('cmd')!='BASE_SPIN':return False
    keys={'accC','accWa','boostData','initialPlayerState','playerState','response'}
    if set(ed) not in (keys,keys|{'nextCmds'}) or not all(_number(ed[k]) for k in ('accC','accWa')):return False
    if 'nextCmds' in ed and command_values(ed['nextCmds']) not in ([],['C']):return False
    boost=ed['boostData']
    if not isinstance(boost,dict) or set(boost)!={'collections','multiplierIncreasedTo5','freeSpinsEntered'} or not _number(boost['collections']) or boost['multiplierIncreasedTo5'] is not False or boost['freeSpinsEntered'] is not False:return False
    states=[]
    for key in ('initialPlayerState','playerState'):
        state=ed[key]
        if not isinstance(state,dict) or set(state)!={'collectionsMap'} or not isinstance(state['collectionsMap'],dict):return False
        maps=state['collectionsMap']
        allowed=(constraints or {}).get('collection_modes',['BASIC','GOLDEN_BET'])
        if not isinstance(allowed,list) or 'BASIC' not in allowed or not all(isinstance(k,str) and k for k in allowed) or not set(maps)<=set(allowed):return False
        for mode,items in maps.items():
            if not isinstance(items,dict) or len(items)>256:return False
            for coin,item in items.items():
                if not _number(coin,positive=True) or not isinstance(item,dict) or set(item)!={'progressLimit','value','progress'}:return False
                if any(type(item[k]) is not int for k in item) or item['progressLimit']<=0 or item['value']<=0 or not 0<=item['progress']<item['progressLimit']:return False
        states.append(maps)
    try:items=[v for k,v in states[-1].get('BASIC',{}).items() if Decimal(k)==Decimal(str(bd['coin']))]
    except (KeyError,InvalidOperation,ValueError,TypeError):return False
    if len(items)!=1:return False
    item=items[0];response=ed['response']
    if not isinstance(response,dict) or set(response)!={'coinWin','cashWin','clientData'} or not all(_number(response[k]) for k in ('coinWin','cashWin')):return False
    cd=response['clientData']
    if not isinstance(cd,dict) or set(cd)!={'actions'} or not isinstance(cd['actions'],list):return False
    normalized=[];seen=False;symbols_by_position={}
    coin=Decimal(str(bd["coin"]))
    if Decimal(str(response['cashWin']))!=Decimal(str(response['coinWin']))*coin:return False
    for action in deepcopy(cd['actions']):
        if not isinstance(action,dict):return False
        if action.get('name')=='showWinResults' and action.get('type')=='collection':
            if Decimal(str(boost['collections']))<=0:return False
            action=_resolved_collection(action,symbols_by_position,coin,Decimal(item['value']))
            if action is None:return False
        if action.get('name')=='setCounters':
            counters=action.get('counters')
            if set(action)!={'name','counters'} or not isinstance(counters,list) or len(counters)!=2:return False
            if not all(isinstance(c,dict) and set(c)=={'name','value'} and isinstance(c['name'],str) for c in counters):return False
            values={c['name']:c['value'] for c in counters}
            if values!={'PROGRESS':item['progress'],'GENERAL_MULTIPLIER':item['value']} or not all(type(c['value']) is int for c in counters):return False
            seen=True;continue
        if action.get('name') in ('stopReels','dropInReels'):
            symbols=action.get('symbols')
            if not isinstance(symbols,list):return False
            seen_positions=set()
            for symbol in symbols:
                if not isinstance(symbol,dict):return False
                pos=symbol.get('position')
                if not isinstance(pos,dict) or set(pos)!={'column','row'} or any(type(v) is not int for v in pos.values()):return False
                coord=(pos['column'],pos['row'])
                if coord in seen_positions:return False
                seen_positions.add(coord)
                symbols_by_position[coord]=deepcopy(symbol)
                if 'value' in symbol:
                    if set(symbol)!={'position','name','value'} or symbol['name']!='CASH':return False
                    money=symbol.pop('value')
                    if not isinstance(money,dict) or set(money)!={'cash','coins'} or not all(_number(v) for v in money.values()):return False
        normalized.append(action)
    if not ordinary_named_actions({'actions':normalized}):return False
    rendered={k:sum((Decimal(str(w['value'][k])) for a in normalized if a.get('name')=='showWinResults' for w in a.get('wins',[]) if isinstance(w,dict) and isinstance(w.get('value'),dict) and _number(w['value'].get(k))),Decimal(0)) for k in ('cash','coins')}
    if rendered!={'cash':Decimal(str(response['cashWin'])),'coins':Decimal(str(response['coinWin']))}:return False
    return (seen or (states[0] == states[1] and boost['collections'] == 0))
