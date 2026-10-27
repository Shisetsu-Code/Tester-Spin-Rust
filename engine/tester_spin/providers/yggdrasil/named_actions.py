"""Recognized named animation outcomes; unrecognized controls stay unknown."""
from decimal import Decimal,InvalidOperation

def _number(v,positive=False):
    if isinstance(v,bool):return False
    try:n=Decimal(str(v))
    except (InvalidOperation,ValueError):return False
    return n.is_finite() and (n>0 if positive else n>=0)

def _money(v):
    if not isinstance(v,dict) or not {'cashWin','coinWin'}<=set(v)<={'cashWin','coinWin','multiplier'}:return False
    if not all(_number(v[k]) for k in ('cashWin','coinWin')):return False
    m=v.get('multiplier')
    return 'multiplier' not in v or isinstance(m,dict) and set(m)=={'value'} and _number(m['value'],positive=True)

def _position(v):
    return isinstance(v,dict) and set(v)=={'column','row'} and all(type(v[k]) is int and 0<=v[k]<limit for k,limit in [('column',20),('row',64)])

def _list(v,check):
    return isinstance(v,list) and len(v)<=256 and all(check(x) for x in v)

def _board(board):
    return (isinstance(board,list) and 1<=len(board)<=20 and all(isinstance(col,list) and 1<=len(col)<=64 and all(isinstance(x,str) and 1<=len(x)<=128 for x in col) for col in board))

def _named_board(value):
    if _board(value):return True
    if not isinstance(value,list) or not value or not all(isinstance(col,list) and col for col in value):return False
    if not all(isinstance(cell,dict) and set(cell)=={'name'} and isinstance(cell['name'],str) for col in value for cell in col):return False
    return len({len(col) for col in value})==1 and _board([[cell['name'] for cell in col] for col in value])

def _wild_life_trace(actions):
    """Observed create(2/3 lives) -> winning cascade -> remaining-name update.

    Track the actual symbol position through simultaneous shifts. A refill or
    an unrelated create cannot silently replace a live wild. This contract is
    intentionally limited to the budgets and names captured in the base trace;
    higher budgets and unexplained upgrades remain unknown.
    """
    special=False
    for action in actions:
        if not isinstance(action,dict):return False
        symbols=action.get('symbols',[])
        if isinstance(symbols,list) and any(isinstance(item,dict) and
                ('lives' in item or item.get('name') in {'WILD_2L','WILD_3L'}) for item in symbols):
            special=True
    if not special:return True
    cells={};lives={};consumed=set();domain=None
    def coordinate(value):
        if not _position(value):return None
        return value['column'],value['row']
    def wild_name(value):return 'WILD' if value==1 else 'WILD_'+str(value)+'L'
    for action in actions:
        name=action.get('name')
        if name=='dropOutReels':
            if consumed:return False
            cells.clear();lives.clear()
        elif name in {'stopReels','dropInReels'}:
            if name=='stopReels':
                if consumed:return False
                cells.clear();lives.clear()
            symbols=action.get('symbols')
            if not isinstance(symbols,list):return False
            for item in symbols:
                if not isinstance(item,dict):return False
                pos=coordinate(item.get('position'))
                if pos is None or name=='dropInReels' and pos not in (domain or set()) or pos in lives or 'lives' in item or item.get('name') in {'WILD_2L','WILD_3L'}:return False
                if item.get('width',1)!=1 or item.get('height',1)!=1:return False
                cells[pos]=item.get('name')
            if name=='stopReels':
                if domain is not None and domain!=set(cells):return False
                domain=set(cells)
        elif name=='pseudoCollection':
            for meter in action.get('pseudoCollectionMeters',[]):
                if not isinstance(meter,dict) or not isinstance(meter.get('positions'),list):return False
                if any(coordinate(value) not in (domain or set()) for value in meter['positions']):return False
        elif name=='setCounters':
            for counter in action.get('counters',[]):
                if not isinstance(counter,dict):return False
                value=counter.get('name')
                if not isinstance(value,str) or not value.isascii() or not value.isdecimal() or not domain or int(value)>max(pos[0] for pos in domain):return False
        elif name=='showWinResults':
            if consumed:return False
            wins=action.get('wins')
            if not isinstance(wins,list):return False
            for win in wins:
                if not isinstance(win,dict) or not isinstance(win.get('positions'),list):return False
                for value in win['positions']:
                    pos=coordinate(value)
                    if pos is None or pos not in cells:return False
                    if pos in lives:
                        if not _number((win.get('value') or {}).get('coins'),positive=True):return False
                        consumed.add(pos)
        elif name=='operateSymbols':
            symbols=action.get('symbols')
            if not isinstance(symbols,list):return False
            operation=action.get('operation')
            for item in symbols:
                if not isinstance(item,dict):return False
                pos=coordinate(item.get('position'));identity=item.get('name')
                if pos is None or pos not in (domain or set()):return False
                if 'lives' in item:
                    if (operation!='create' or identity!='WILD' or item.get('subsymbol') is not False
                            or type(item['lives']) is not int or item['lives'] not in {2,3} or pos in cells):return False
                    lives[pos]=item['lives'];cells[pos]=wild_name(item['lives'])
                elif operation=='create':
                    if pos in lives:
                        if pos not in consumed or lives[pos]<=1 or identity!=wild_name(lives[pos]-1):return False
                        lives[pos]-=1;consumed.remove(pos)
                    elif identity in {'WILD_2L','WILD_3L'}:return False
                    elif identity=='WILD':
                        if pos in cells:return False
                        lives[pos]=1
                    cells[pos]=identity
                elif operation=='remove':
                    if cells.get(pos)!=identity:return False
                    if pos in lives:
                        if lives[pos]!=1 or pos not in consumed:return False
                        lives.pop(pos);consumed.remove(pos)
                    cells.pop(pos,None)
                else:return False
        elif name=='destroySymbols':
            positions=action.get('positions')
            if not isinstance(positions,list):return False
            for value in positions:
                pos=coordinate(value)
                if pos is None or pos not in (domain or set()) or pos in lives:return False
                cells.pop(pos,None)
        elif name in {'bringNewSymbols','fillSymbols'}:
            symbols=action.get('symbols')
            if not isinstance(symbols,list):return False
            for item in symbols:
                if not isinstance(item,dict):return False
                pos=coordinate(item.get('position'))
                if pos is None or pos not in (domain or set()) or pos in cells:return False
                cells[pos]=item.get('type')
        elif name=='shiftSymbols':
            shifts=action.get('positionShifts')
            if not isinstance(shifts,list):return False
            pairs=[]
            for shift in shifts:
                if not isinstance(shift,dict):return False
                origin=coordinate(shift.get('origin'));target=coordinate(shift.get('target'))
                if origin is None or target is None or origin not in cells or target not in (domain or set()):return False
                pairs.append((origin,target))
            origins={origin for origin,target in pairs};targets={target for origin,target in pairs}
            if len(origins)!=len(pairs) or len(targets)!=len(pairs):return False
            if any(target in cells and target not in origins for target in targets):return False
            moved={target:cells[origin] for origin,target in pairs}
            moved_lives={target:lives[origin] for origin,target in pairs if origin in lives}
            moved_consumed={target for origin,target in pairs if origin in consumed}
            for pos in origins|targets:cells.pop(pos,None);lives.pop(pos,None);consumed.discard(pos)
            cells.update(moved);lives.update(moved_lives);consumed.update(moved_consumed)
    return not consumed


def ordinary_named_actions(cd, *, wild_life_bound=False):
    if not {'actions'}<=set(cd)<={'actions','finalBoard','wonCoins','wonMoney'}:return False
    if not all(_number(cd[k]) for k in ('wonCoins','wonMoney') if k in cd):return False
    if 'finalBoard' in cd and not _board(cd['finalBoard']):return False
    actions=cd['actions'];seen_board=False
    created_multipliers={}
    if not isinstance(actions,list) or not 1<=len(actions)<=256:return False
    if _has_wild_lives(actions) and not wild_life_bound:return False
    if not _wild_life_trace(actions):return False
    for a in actions:
        if not isinstance(a,dict):return False
        name=a.get('name')
        if not isinstance(name,str):return False
        if name=='finishSpin':
            if set(a)!={'name','winCounters'}:return False
            a={'name':'setWinCounters','counters':a['winCounters']};name='setWinCounters'

        if name in {'spinReels','dropOutReels'}:
            if name=='dropOutReels':created_multipliers.clear()
            if set(a)=={'name','boardName'}:
                if a['boardName']!='':return False
            elif set(a)=={'name','syncedReels'}:
                reels=a['syncedReels']
                if not isinstance(reels,list) or not 1<=len(reels)<=20 or not all(type(r) is int and 0<=r<20 for r in reels) or len(set(reels))!=len(reels):return False
            elif set(a)!={'name'}:return False
        elif name in {'stopReels','dropInReels'}:
            if name=='stopReels':created_multipliers.clear()
            if set(a)=={'name','symbols'}:
                symbols=a['symbols']
                if not isinstance(symbols,list) or not 1<=len(symbols)<=1280:return False
                positions=[]
                for symbol in symbols:
                    if not isinstance(symbol,dict) or set(symbol) not in ({'position','subsymbol','name'},{'position','name'},{'position','name','height','width'},{'position','name','subSymbol'},{'position','name','side'}) or type(symbol.get('subsymbol',False)) is not bool or not _position(symbol['position']) or not isinstance(symbol['name'],str) or not 1<=len(symbol['name'])<=128:return False
                    if 'subSymbol' in symbol and symbol['subSymbol']!='SINGLE':return False
                    if 'side' in symbol and symbol['side'] not in ('LEFT','RIGHT'):return False
                    w=symbol.get('width',1);h=symbol.get('height',1)
                    if type(w) is not int or type(h) is not int or not 1<=w<=20 or not 1<=h<=64:return False
                    x=symbol['position']['column'];y=symbol['position']['row']
                    created_multipliers.pop((x,y),None)
                    if x+w>20 or y+h>64:return False
                    positions.extend((x+dx,y+dy) for dx in range(w) for dy in range(h))
                width=max(x for x,y in positions)+1;height=max(y for x,y in positions)+1
                if len(set(positions))!=len(positions):return False
                if name=='stopReels' or not seen_board:
                    if set(positions)!={(x,y) for x in range(width) for y in range(height)}:return False
                seen_board=True
                continue
            board=a.get('board')
            if set(a)!={'name','board'} or not _named_board(board):return False
            seen_board=True
        elif name in {'showAvalancheAccumulatedWin','showAccumulatedWin'}:
            if set(a)!={'name','win'} or not _money(a['win']):return False
        elif name=='showWinResult':
            if (not {'name','positions','win'}<=set(a)<={'name','positions','win','totalFreeSpinsWin'}
                    or not _list(a['positions'],_position) or not _list(a['win'],_money)
                    or 'totalFreeSpinsWin' in a and not _money(a['totalFreeSpinsWin'])):return False
        elif name=='gigabloxReels':
            if set(a)!={'name','gigabloxData'} or not isinstance(a['gigabloxData'],list) or len(a['gigabloxData'])>20:return False
            for item in a['gigabloxData']:
                if not isinstance(item,dict) or set(item)!={'column','width'} or type(item['column']) is not int or type(item['width']) is not int or not 0<=item['column']<20 or not 1<=item['width']<=20 or item['column']+item['width']>20:return False
        elif name=='showWinResults':
            if set(a) not in ({'name','type','wins','isOverWinCap'},{'name','type','wins'}) or a['type'] not in ('regular','chain') or a.get('isOverWinCap',False) is not False:return False
            wins=a['wins']
            if not isinstance(wins,list) or len(wins)>256:return False
            for win in wins:
                if not isinstance(win,dict) or set(win) not in ({'value','multiplier','positions','symbol','oak','direction','paylineIndex'},{'value','initialValue','multiplier','positions','symbol','oak','direction','ways'},{'value','multiplier','positions','symbol','oak','direction','ways'},{'value','multiplier','positions','symbol','oak'},{'value','initialValue','multiplier','positions','symbol','oak'},{'value','multiplier','positions','symbol','oak','ways'}):return False
                if 'initialValue' in win and (not isinstance(win['initialValue'],dict) or set(win['initialValue'])!={'cash','coins'} or not all(_number(v) for v in win['initialValue'].values()) or 'ways' in win and (type(win['ways']) is not int or win['ways']<=0)):return False
                value=win['value']
                if not isinstance(value,dict) or set(value)!={'cash','coins'} or not all(_number(x) for x in value.values()) or not _number(win['multiplier'],positive=True):return False
                if 'ways' in win and (type(win['ways']) is not int or win['ways']<=0):return False
                if not _list(win['positions'],_position) or not win['positions'] or not isinstance(win['symbol'],str) or not win['symbol'] or type(win['oak']) is not int or win['oak']<=0 or ('paylineIndex' in win and (type(win['paylineIndex']) is not int or win['paylineIndex']<0)) or ('direction' in win and (not isinstance(win['direction'],str) or win['direction'] not in {'LEFT_TO_RIGHT','RIGHT_TO_LEFT'})):return False
        elif name=='setCounters':
            if set(a)!={'name','counters'} or not isinstance(a['counters'],list) or len(a['counters'])!=1:return False
            counter=a['counters'][0]
            if not isinstance(counter,dict) or set(counter)!={'name','value'} or not isinstance(counter['name'],str) or (counter['name'] not in {'wildMultiplier','globalMultiplier'} and not (len(counter['name'])<=2 and counter['name'].isascii() and counter['name'].isdecimal() and 0<=int(counter['name'])<20)) or not _number(counter['value'],positive=True):return False
        elif name=='setWinCounters':
            if set(a)!={'name','counters'} or not isinstance(a['counters'],list) or not 1<=len(a['counters'])<=4:return False
            names=[]
            for counter in a['counters']:
                if not isinstance(counter,dict) or set(counter) not in ({'name','value'},{'name','value','multiplier'}) or not isinstance(counter['name'],str) or counter['name'] not in {'currentWin','spinWin','totalWin','freeSpinsWin'}:return False
                names.append(counter['name'])
                value=counter['value']
                if not isinstance(value,dict) or set(value)!={'cash','coins'} or not all(_number(x) for x in value.values()) or 'multiplier' in counter and not _number(counter['multiplier'],positive=True):return False
                if counter['name']=='freeSpinsWin' and any(Decimal(str(v))!=0 for v in value.values()):return False
            if len(set(names))!=len(names):return False
            if 'freeSpinsWin' in names and set(names)!={'currentWin','spinWin','totalWin','freeSpinsWin'}:return False
        elif name=='showInfo':
            if a!={'name':'showInfo','key':'louder','value':'1'}:return False
        elif name=='setCollections':
            if set(a)!={'name','collections'} or not isinstance(a['collections'],list) or not 1<=len(a['collections'])<=256:return False
            names=[]
            for item in a['collections']:
                if not isinstance(item,dict) or set(item)!={'name','value'} or not isinstance(item['name'],str) or not _number(item['name'],positive=True) or type(item['value']) is not int or item['value']<0:return False
                names.append(item['name'])
            if len(set(names))!=len(names):return False
        elif name=='setReelsMultiplier':
            if set(a)!={'name','reelsMultipliers'} or not isinstance(a['reelsMultipliers'],list) or not 1<=len(a['reelsMultipliers'])<=20:return False
            reels=[]
            for item in a['reelsMultipliers']:
                if not isinstance(item,dict) or set(item)!={'reel','multiplier'} or type(item['reel']) is not int or not 0<=item['reel']<20 or not _number(item['multiplier'],positive=True):return False
                reels.append(item['reel'])
            if len(set(reels))!=len(reels):return False
        elif name=='pseudoCollection':
            if set(a)!={'name','pseudoCollectionMeters'} or not isinstance(a['pseudoCollectionMeters'],list) or len(a['pseudoCollectionMeters'])>256:return False
            for item in a['pseudoCollectionMeters']:
                if not isinstance(item,dict) or set(item)!={'name','level','positions','jackpot'} or not isinstance(item['name'],str) or not item['name'] or type(item['level']) is not int or item['level']<0 or item['jackpot'] is not False or not _list(item['positions'],_position):return False
        elif name=='operateSymbols':
            if set(a) not in ({'name','operation','symbols'},{'name','operation','symbols','reveledMysterySymbols'}) or a.get('operation') not in ('remove','splitGigablox','create') or a.get('reveledMysterySymbols',[])!=[]:return False
            symbols=a['symbols']
            if not isinstance(symbols,list) or not 1<=len(symbols)<=1280:return False
            for item in symbols:
                if not isinstance(item,dict) or set(item) not in ({'position','name'},{'position','name','subsymbol'},{'position','name','subsymbol','multiplier'},{'position','name','height','width'},{'position','name','subsymbol','lives'}) or not _position(item['position']) or not isinstance(item['name'],str) or not item['name'] or item.get('subsymbol',False) is not False:return False
                if 'lives' in item and (a['operation']!='create' or item['name']!='WILD' or type(item['lives']) is not int or item['lives'] not in {2,3}):return False
                coordinate=(item['position']['column'],item['position']['row'])
                if a['operation']=='create':created_multipliers.pop(coordinate,None)
                if 'multiplier' in item:
                    if not _number(item['multiplier'],positive=True):return False
                    identity=(item['name'],Decimal(str(item['multiplier'])))
                    if a['operation']=='create':created_multipliers[coordinate]=identity
                    elif a['operation']!='remove' or created_multipliers.get(coordinate)!=identity:return False
                if a['operation']=='remove':created_multipliers.pop(coordinate,None)
                if a['operation']=='splitGigablox' and set(item)!={'position','name','height','width'}:return False
                if 'width' in item and (type(item['width']) is not int or type(item['height']) is not int or not 1<=item['width']<=20 or not 1<=item['height']<=64 or item['position']['column']+item['width']>20 or item['position']['row']+item['height']>64):return False
        elif name=='destroySymbols':
            if set(a)!={'name','positions'} or not _list(a['positions'],_position):return False
        elif name in {'bringNewSymbols','fillSymbols'}:
            def symbol(x):return isinstance(x,dict) and set(x)=={'position','type'} and _position(x['position']) and isinstance(x['type'],str) and 1<=len(x['type'])<=128
            if set(a)!={'name','symbols'} or not _list(a['symbols'],symbol):return False
        elif name=='shiftSymbols':
            def shift(x):return isinstance(x,dict) and set(x)=={'origin','target'} and all(_position(p) for p in x.values())
            if set(a)!={'name','positionShifts'} or not _list(a['positionShifts'],shift):return False
            moved={};origins=set();targets=set()
            for item in a['positionShifts']:
                origin=(item['origin']['column'],item['origin']['row'])
                target=(item['target']['column'],item['target']['row'])
                if origin in origins or target in targets:return False
                origins.add(origin);targets.add(target)
                if origin in created_multipliers:
                    if target in moved:return False
                    moved[target]=created_multipliers[origin]
            for position in origins|targets:created_multipliers.pop(position,None)
            created_multipliers.update(moved)
        elif name=='setGlobalMultiplier':
            if set(a)!={'name','multiplier'} or not _number(a['multiplier'],positive=True):return False
        else:return False
    return seen_board


def _has_wild_lives(actions):
    return isinstance(actions,list) and any(isinstance(action,dict) and isinstance(action.get('symbols'),list)
        and any(isinstance(symbol,dict) and ('lives' in symbol or symbol.get('name') in {'WILD_2L','WILD_3L'})
                for symbol in action['symbols']) for action in actions)


def _life_number(value):
    if not _number(value):raise ValueError('invalid wild-life amount')
    return Decimal(str(value))


def ordinary_wild_life_round(bet,constraints):
    """Bind the captured base-only lifetime DTO to its cash/cascade envelope."""
    try:
        bd,ed=bet['betdata'],bet['eventdata'];response=ed['response'];cd=response['clientData']
        if (not isinstance(constraints,dict) or type(bet['step']) is not int or bet['step']!=1
                or bet['status']!='RESULTED' or bet['betcurrency']!=constraints['currency']
                or _life_number(bet['wonamount'])!=0 or bet.get('prizes') is not None or bet.get('prepaid') is not False or bd['cmd']!='BASE_SPIN'
                or not _has_wild_lives(cd.get('actions')) or set(cd)!={'actions'}
                or not ordinary_named_actions(cd,wild_life_bound=True)):
            return False
        if set(bd)!={'coin','cashBet','initialBalance','cmd','accWa','accC','cmds'} or bd['cmds']!=['C']:
            return False
        coin=_life_number(bd['coin']);stake=_life_number(bd['cashBet'])
        if (coin<=0 or stake<=0 or coin!=_life_number(constraints['basic_coin'])
                or stake!=_life_number(constraints['basic_amount']) or stake!=_life_number(bet['betamount'])):
            return False
        _life_number(bd['initialBalance'])
        if (set(ed)!={'accC','accWa','boostData','initialPlayerState','nextCmds','playerState','response'}
                or ed['nextCmds']!='C' or set(response)!={'coinWin','cashWin','clientData'}):return False
        actions=cd['actions']
        allowed={'spinReels','stopReels','dropInReels','pseudoCollection','showWinResults','setWinCounters','operateSymbols','shiftSymbols','setCounters'}
        if any(a['name'] not in allowed for a in actions):return False
        wins=[a for a in actions if a['name']=='showWinResults']
        boosts=ed['boostData']
        if set(boosts)!={'boostDatas'} or not isinstance(boosts['boostDatas'],list) or len(boosts['boostDatas'])!=len(wins)+1:return False
        for index,boost in enumerate(boosts['boostDatas']):
            if (set(boost)!={'respinNumber','gameMode','lastRespin','randomWinFeature'}
                    or type(boost['respinNumber']) is not int or boost['respinNumber']!=index
                    or boost['gameMode']!='BASE_GAME' or boost['lastRespin'] is not (index==len(wins))
                    or boost['randomWinFeature'] is not None):return False
        cash=coins=Decimal(0);current_cash=current_coins=Decimal(0);counters=0
        for action in actions:
            if action['name']=='showWinResults':
                current_cash=current_coins=Decimal(0)
                for win in action['wins']:
                    value=win['value'];part_cash=_life_number(value['cash']);part_coins=_life_number(value['coins'])
                    if part_cash!=part_coins*coin:return False
                    if 'initialValue' in win and any(_life_number(win['initialValue'][key])*_life_number(win['multiplier'])!=_life_number(value[key]) for key in ('cash','coins')):return False
                    current_cash+=part_cash;current_coins+=part_coins
                cash+=current_cash;coins+=current_coins
            elif action['name']=='setWinCounters':
                values={counter['name']:counter['value'] for counter in action['counters']}
                if set(values)!={'currentWin','spinWin','totalWin'}:return False
                for name,value in values.items():
                    expected=(current_cash,current_coins) if name=='currentWin' else (cash,coins)
                    if (_life_number(value['cash']),_life_number(value['coins']))!=expected:return False
                counters+=1
        if counters!=len(wins):return False
        if any(_life_number(value)!=cash for value in (bd['accWa'],ed['accWa'],response['cashWin'])):return False
        if any(_life_number(value)!=coins for value in (bd['accC'],ed['accC'],response['coinWin'])):return False
        initial,final=ed['initialPlayerState'],ed['playerState']
        for state in (initial,final):
            if set(state)!={'totalWin','pseudoCollectionProgresses','commands'} or state['commands']!=['BASIC']:return False
            progress=state['pseudoCollectionProgresses']
            if not isinstance(progress,dict) or not progress or len(progress)>256:return False
            for name,value in progress.items():
                if not isinstance(name,str) or not name or set(value)!={'level','subsymbols'} or any(type(n) is not int or n<0 for n in value.values()):return False
        if _life_number(initial['totalWin'])!=0 or _life_number(final['totalWin'])!=coins:return False
        start,end=initial['pseudoCollectionProgresses'],final['pseudoCollectionProgresses']
        if set(start)!=set(end):return False
        increments={name:0 for name in start}
        for action in actions:
            if action['name']=='pseudoCollection':
                for meter in action['pseudoCollectionMeters']:
                    name=meter['name']
                    if name not in start or meter['level']!=start[name]['level']:return False
                    increments[name]+=len(meter['positions'])
        return all(end[name]['level']==start[name]['level'] and end[name]['subsymbols']==start[name]['subsymbols']+increments[name] for name in start)
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError,ArithmeticError):return False


def validate_wild_life_collect(before,after,request,constraints):
    """Only the bound base lifetime family may use this accumulated-win receipt."""
    roots=before.get('bets',[])
    if len(roots)!=1:return
    root=roots[0];bd=root.get('betdata') or {};ed=root.get('eventdata') or {}
    cd=(ed.get('response') or {}).get('clientData') or {}
    if bd.get('cmd')!='BASE_SPIN' or not _has_wild_lives(cd.get('actions')):return
    try:
        if not ordinary_wild_life_round(root,constraints):raise ValueError('unbound root')
        if request['cmd']!='C' or before['wagerid']!=after['wagerid'] or not after['terminal'] or len(after['bets'])!=1:raise ValueError('unbound receipt')
        receipt=after['bets'][0];collected=receipt['betdata'];event=receipt['eventdata']
        amount=_life_number(ed['response']['cashWin']);coins=_life_number(ed['response']['coinWin'])
        if (receipt['step']!=root['step']+1 or receipt['status']!='RESULTED'
                or _life_number(receipt['betamount'])!=0 or receipt['betcurrency']!=root['betcurrency']
                or set(collected)!={'coin','cashBet','cmd','accWa','accC'} or collected['cmd']!='C'
                or any(_life_number(collected[key])!=_life_number(bd[key]) for key in ('coin','cashBet'))
                or set(event)!={'exactWon'} or _life_number(collected['accC'])!=coins
                or receipt.get('prepaid') is not False
                or any(_life_number(value)!=amount for value in (receipt['wonamount'],collected['accWa'],event['exactWon']))):raise ValueError('inconsistent receipt')
        prizes=receipt.get('prizes')
        if not isinstance(prizes,list) or len(prizes)!=1:raise ValueError('unbound cash prize')
        prize=prizes[0]
        if (not isinstance(prize,dict) or set(prize)!={'prizeid','type','descr','wonamount','netamount','woncurrency','gameId','wonAspect','prizedata'}
                or not isinstance(prize['prizeid'],str) or not prize['prizeid'] or prize['type']!='FIXED'
                or not isinstance(prize['descr'],str) or type(prize['gameId']) is not int or prize['gameId']<=0
                or prize['wonAspect']!='CASH' or prize['woncurrency']!=root['betcurrency'] or prize['prizedata'] is not None
                or any(_life_number(prize[key])!=amount for key in ('wonamount','netamount'))):raise ValueError('inconsistent cash prize')
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError,ArithmeticError):
        raise ValueError('Wild-life base collect settlement mismatch') from None
