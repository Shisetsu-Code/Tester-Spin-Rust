"""Current settings mode contracts and independently reconciled paid receipts."""
from collections import Counter
from .runtime import _decimal


def declared_modifiers(game):
    entries=game.get('gameModes')
    if not isinstance(entries,list):return [],[]
    math=game.get('mathModes');math=math if isinstance(math,list) else []
    ids=Counter(row.get('gameMode') for row in entries if isinstance(row,dict) and type(row.get('gameMode')) is int)
    result=[];unknown=[]
    for row in entries:
        if isinstance(row,dict) and type(row.get('gameMode')) is int and row['gameMode']==0:continue
        if not isinstance(row,dict):unknown.append(row);continue
        selector=row.get('gameMode');name=row.get('name');price=None if isinstance(row.get('priceMultiplier'),bool) else _decimal(row.get('priceMultiplier'))
        matches=[m for m in math if isinstance(m,dict) and type(m.get('id')) is int and m['id']==selector]
        if (type(selector) is not int or selector<=0 or ids[selector]!=1 or len(matches)!=1
                or not isinstance(name,str) or not name.strip() or price is None or price<=0):
            unknown.append(row);continue
        match=matches[0]
        effective=None if isinstance(match.get('priceMultiplier'),bool) else _decimal(match.get('priceMultiplier'))
        if (match.get('type') not in ('chanceIncrease','stateSwitch') or match.get('name')!=name or effective!=price):
            unknown.append(row);continue
        result.append({'kind':'ANTE_BET' if match['type']=='chanceIncrease' else 'STATE_SWITCH',
            'gameMode':selector,'price_multiplier':str(price),'name':name,'server_type':match['type'],
            'source':'SETTINGS.game.gameModes_and_mathModes_exact_match'})
    return result,unknown


def modifier_domains(game):
    """Declare both modifier categories, including independently proven zero."""
    entries=game.get('gameModes');math=game.get('mathModes')
    complete=isinstance(entries,list) and isinstance(math,list)
    modifiers,unknown=declared_modifiers(game)
    complete=complete and not unknown
    selectors={row.get('gameMode') for row in entries if isinstance(row,dict)} if isinstance(entries,list) else set()
    if isinstance(math,list):
        for row in math:
            if not isinstance(row,dict):complete=False;continue
            if row.get('type') in ('chanceIncrease','stateSwitch') and row.get('id') not in selectors:
                complete=False
    return {category:{'complete':complete,'source':'SETTINGS.game.gameModes_and_mathModes_exact_match',
                       'options':[str(m['gameMode']) for m in modifiers if m['kind']==kind]}
            for category,kind in (('ante','ANTE_BET'),('special','STATE_SWITCH'))}


def modifier_executed(payload,request,spec):
    if payload.get('success') is not True:return False
    try:
        stake=_decimal(request.get('stake'));price=_decimal(spec['price_multiplier'])
        if (request.get('gameMode')!=spec['gameMode'] or request.get('extras') not in (None,{})
                or request.get('bonusId') is not None or stake is None or stake<=0 or price is None or price<=0):return False
        game=payload['result']['game'];cash=payload['result']['user']['balance']['cash']
        if type(game.get('gameMode')) is not int or game['gameMode']!=spec['gameMode'] or _decimal(game.get('stake'))!=stake:return False
        values=[_decimal(cash.get(k)) for k in ('atStart','afterBet','atEnd')];win=_decimal(game.get('win',{}).get('total'))
        if any(v is None for v in values) or win is None or win<0:return False
        start,after,end=values
        return start-after==stake*price and end-after==win
    except (KeyError,TypeError,AttributeError):return False
