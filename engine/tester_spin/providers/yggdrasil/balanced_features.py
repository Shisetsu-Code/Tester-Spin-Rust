"""Closed typed base animation cycles, distinct from pending selectors."""
import re
from .named_actions import _number

def _positions(v):
    return isinstance(v,list) and len(v)<=1280 and all(isinstance(p,dict) and set(p)=={'x','y'} and type(p['x']) is int and type(p['y']) is int and 0<=p['x']<20 and 0<=p['y']<64 for p in v)

def _cells(v):
    if not isinstance(v,list) or len(v)>1280:return False
    for cell in v:
        if not isinstance(cell,dict) or set(cell) not in ({'position','symbol'},{'position','symbol','counters'}):return False
        if not _positions([cell['position']]) or cell.get('counters',[])!=[]:return False
        sym=cell['symbol']
        if not isinstance(sym,dict) or set(sym)!={'symbolCode','counters'} or sym['counters']!=[] or not isinstance(sym['symbolCode'],str) or not 1<=len(sym['symbolCode'])<=128:return False
    return True

def _win(v):
    return isinstance(v,dict) and set(v)=={'currency','amount','amountNormalizedToBet'} and isinstance(v['currency'],str) and bool(re.fullmatch(r'[A-Z]{3}',v['currency'])) and _number(v['amount']) and _number(v['amountNormalizedToBet'])

def ordinary_balanced_features(cd):
    if set(cd)!={'actions','isFinished'} or cd['isFinished'] is not True:return False
    actions=cd['actions']
    if not isinstance(actions,list) or not 1<=len(actions)<=256:return False
    minimal={'ActionGame_PresentModeStart':{'$type','modeName'},'ActionGame_NewSpin':{'$type'},'ActionGame_FeatureHappened':{'$type','featureIdentifier'},'ActionGame_PresentModeWin':{'$type'}}
    if all(isinstance(a,dict) and isinstance(a.get('$type'),str) and a.get('$type') in minimal and set(a)==minimal[a['$type']] for a in actions):
        modes=[a['modeName'] for a in actions if a['$type']=='ActionGame_PresentModeStart']
        features=[a['featureIdentifier'] for a in actions if a['$type']=='ActionGame_FeatureHappened']
        return bool(modes) and all(m=='BaseGame' for m in modes) and bool(features) and all(f=='spin' for f in features) and any(a['$type']=='ActionGame_NewSpin' for a in actions)
    fields={'ActionGame_PresentModeStart':{'modeName'},'ActionGame_NewSpin':{'board'},
            'ActionGame_SetCounterBoard':{'name','value'},'ActionGame_FeatureHappened':{'featureIdentifier'},
            'ActionGame_SymbolsSet':{'cells'},'ActionGame_PresentWinCombination':{'win','winningCells'},
            'ActionGame_PresentModeWin':{'modeWin','accumulatedRoundWin'}}
    active=set();modes=0;spins=0;spin_feature=False
    for a in actions:
        if not isinstance(a,dict):return False
        typ=a.get('$type')
        if not isinstance(typ,str) or typ not in fields or set(a)!=fields[typ]|{'$type','animationIdentifier','actionSource'}:return False
        source=a['actionSource']
        if source!={'$type':'ActionSource_Empty'} and not (isinstance(source,dict) and set(source)=={'$type','positions'} and source['$type']=='ActionSource_Positions' and _positions(source['positions'])):return False
        if not isinstance(a['animationIdentifier'],str):return False
        if typ=='ActionGame_PresentModeStart':
            if a['modeName']!='BaseGame':return False
            modes+=1
        elif typ=='ActionGame_NewSpin':
            if not isinstance(a['board'],dict) or set(a['board'])!={'cells','counters'} or a['board']['counters']!=[] or not a['board']['cells'] or not _cells(a['board']['cells']):return False
            spins+=1
        elif typ=='ActionGame_SetCounterBoard':
            if not isinstance(a['name'],str) or not _number(a['value']):return False
            if a['name']=='C_FreeSpinsLeft':
                if a['value']!=0:return False
            elif a['name'] in {'C_Multiplier','Doublemax'} or re.fullmatch(r'MultiplierReel(?:[0-9]|1[0-9])',a['name']):
                if not _number(a['value'],positive=True):return False
            elif re.fullmatch(r'NumberOfSymbols[0-9]{1,2}',a['name']):
                if int(a['name'][len('NumberOfSymbols'):])>=20 or type(a['value']) is not int:return False
            else:return False
        elif typ=='ActionGame_SymbolsSet':
            if not _cells(a['cells']):return False
        elif typ=='ActionGame_PresentWinCombination':
            if not _win(a['win']) or not _positions(a['winningCells']):return False
        elif typ=='ActionGame_PresentModeWin':
            if not _win(a['modeWin']) or not _win(a['accumulatedRoundWin']):return False
        elif typ=='ActionGame_FeatureHappened':
            label=a['featureIdentifier']
            if not isinstance(label,str):return False
            if label.lower()=='spin':spin_feature=True
            elif re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}On',label):
                key=label[:-2]
                if key in active:return False
                active.add(key)
            elif re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}Off',label):
                key=label[:-3]
                if key not in active:return False
                active.remove(key)
            else:return False
    return modes>0 and spins==1 and not active
