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

def ordinary_named_actions(cd):
    if not {'actions'}<=set(cd)<={'actions','finalBoard','wonCoins','wonMoney'}:return False
    if not all(_number(cd[k]) for k in ('wonCoins','wonMoney') if k in cd):return False
    if 'finalBoard' in cd and not _board(cd['finalBoard']):return False
    actions=cd['actions'];seen_board=False
    if not isinstance(actions,list) or not 1<=len(actions)<=256:return False
    for a in actions:
        if not isinstance(a,dict):return False
        name=a.get('name')
        if not isinstance(name,str):return False
        if name=='finishSpin':
            if set(a)!={'name','winCounters'}:return False
            a={'name':'setWinCounters','counters':a['winCounters']};name='setWinCounters'

        if name in {'spinReels','dropOutReels'}:
            if set(a)=={'name','boardName'}:
                if a['boardName']!='':return False
            elif set(a)=={'name','syncedReels'}:
                reels=a['syncedReels']
                if not isinstance(reels,list) or not 1<=len(reels)<=20 or not all(type(r) is int and 0<=r<20 for r in reels) or len(set(reels))!=len(reels):return False
            elif set(a)!={'name'}:return False
        elif name in {'stopReels','dropInReels'}:
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
                if not isinstance(item,dict) or set(item) not in ({'position','name'},{'position','name','subsymbol'},{'position','name','subsymbol','multiplier'},{'position','name','height','width'}) or not _position(item['position']) or not isinstance(item['name'],str) or not item['name'] or item.get('subsymbol',False) is not False:return False
                if 'multiplier' in item and (a['operation']!='create' or not _number(item['multiplier'],positive=True)):return False
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
        elif name=='setGlobalMultiplier':
            if set(a)!={'name','multiplier'} or not _number(a['multiplier'],positive=True):return False
        else:return False
    return seen_board
