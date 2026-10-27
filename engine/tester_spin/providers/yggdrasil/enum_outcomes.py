"""Numeric round DTO: main mode 0, ERoundTypes.Regular=0 in the official SDK."""
from .named_actions import _number
from decimal import Decimal

def _ints(values,limit=256):
    return isinstance(values,list) and len(values)<=limit and all(type(x) is int and x>=0 for x in values)

def _grid(grid):
    return isinstance(grid,list) and 1<=len(grid)<=20 and all(isinstance(col,list) and 1<=len(col)<=64 and all(type(x) is int and 0<=x<=4096 for x in col) for col in grid)

def _line_prizes(prizes,grid,lines):
    if not isinstance(prizes,list) or len(prizes)>256:return False
    fields={'PrizeType','Value','RawValue','Rule','Combination','Length','Line','Source','Cells'}
    for prize in prizes:
        if not isinstance(prize,dict) or set(prize)!=fields or type(prize['PrizeType']) is not int or prize['PrizeType']!=10:return False
        if any(type(prize[k]) is not int or prize[k]<0 for k in ('Rule','Combination','Length','Line','Source')) or not 1<=prize['Length']<=len(grid) or prize['Line']>lines:return False
        if not all(_number(prize[k]) for k in ('Value','RawValue')):return False
        cells=prize['Cells']
        if not isinstance(cells,list) or len(cells)!=prize['Length']:return False
        for cell in cells:
            if not _ints(cell,2) or len(cell)!=2 or cell[0]>=len(grid) or cell[1]>=len(grid[cell[0]]):return False
        if len({tuple(cell) for cell in cells})!=len(cells):return False
    return True


def ordinary_enum_round(cd):
    if not isinstance(cd,dict) or set(cd)!={'Code','Completed','Bet','Round'} or type(cd['Code']) is not int or cd['Code']!=2001 or cd['Completed'] is not True:return False
    bet=cd['Bet'];round=cd['Round']
    if not isinstance(bet,dict) or set(bet)!={'Lines','FeeMultiplier','Amount','GameMode','Scale','TotalBet'} or type(bet['GameMode']) is not int or bet['GameMode']!=0 or type(bet['Lines']) is not int or not 1<=bet['Lines']<=4096 or not all(_number(bet[k],positive=True) for k in ('FeeMultiplier','Amount','Scale','TotalBet')):return False
    if not isinstance(round,dict) or set(round) not in ({'Info','VISData'},{'Info','VISData','TotalWin','SpinWin'}):return False
    info=round['Info'];vis=round['VISData']
    if not isinstance(info,dict) or set(info)!={'RID','SRC','IDX','GameMode','RoundType','Count','Passed','Bet'}:return False
    if not all(type(info[k]) is int and info[k]>=0 for k in ('RID','SRC','IDX','GameMode','RoundType','Count','Passed')) or any(info[k]!=0 for k in ('GameMode','RoundType','Count')) or info['Passed']!=1 or not _number(info['Bet'],positive=True):return False
    if not isinstance(vis,dict) or set(vis) not in ({'Grids','Prizes','Events','FEV'},{'Grids','Prizes','Events'}):return False
    grids=vis['Grids'];events=vis['Events'];fev=vis.get('FEV',{})
    if not isinstance(grids,list) or not 1<=len(grids)<=256 or not all(_grid(g) for g in grids) or not isinstance(events,list) or not 1<=len(events)<=256 or not isinstance(fev,dict):return False
    if any([len(col) for col in g]!=[len(col) for col in grids[0]] for g in grids):return False
    if not _line_prizes(vis['Prizes'],grids[0],bet['Lines']):return False
    if vis['Prizes'] and 'TotalWin' not in round:return False
    if 'TotalWin' in round:
        total=sum((Decimal(str(p['Value'])) for p in vis['Prizes']),Decimal(0))
        if not all(_number(round[k]) and Decimal(str(round[k]))==total for k in ('TotalWin','SpinWin')):return False
    for event in events:
        if not isinstance(event,dict) or type(event.get('Type')) is not int:return False
        typ=event['Type']
        if typ==10:
            if set(event) not in ({'Type','SymbolKit','Grids'},{'Type','SymbolKit','ReelStops','Grids'}) or type(event['SymbolKit']) is not int or event['SymbolKit']<0 or not _ints(event['Grids']) or not event['Grids'] or any(i>=len(grids) for i in event['Grids']):return False
            if 'ReelStops' in event and (not _ints(event['ReelStops'],20) or len(event['ReelStops'])!=len(grids[event['Grids'][0]])):return False
        elif typ==20:
            if set(event) not in ({'Type','Rules'},{'Type','Rules','Grid'},{'Type','Rules','Grid','Prizes'}) or not _ints(event['Rules']):return False
            if 'Grid' in event:
                if type(event['Grid']) is not int or not 0<=event['Grid']<len(grids):return False
                if 'Prizes' in event:
                    window=event['Prizes']
                    if not _ints(window,2) or len(window)!=2 or sum(window)>len(vis['Prizes']):return False
                elif vis['Prizes']:return False
        elif typ==50:
            if set(event)!={'Type','SwappedSymbols'} or not isinstance(event['SwappedSymbols'],list) or len(event['SwappedSymbols'])>1280:return False
            if not all(_ints(x,3) and len(x)==3 and x[0]<=4096 and x[1]<len(grids[0]) and x[2]<len(grids[0][x[1]]) for x in event['SwappedSymbols']):return False
        elif typ==60:
            if set(event)!={'Type','Expansion','Positions','Grid'} or type(event['Expansion']) is not int or event['Expansion']!=3 or type(event['Grid']) is not int or not 0<=event['Grid']<len(grids):return False
            groups=event['Positions'];grid=grids[event['Grid']]
            if not isinstance(groups,list) or not 0<=len(groups)<=256:return False
            for group in groups:
                if not isinstance(group,list) or not 1<=len(group)<=1280:return False
                for cell in group:
                    if not _ints(cell,2) or len(cell)!=2 or cell[0]>=len(grid) or cell[1]>=len(grid[cell[0]]):return False
        elif typ==201:
            if set(event)=={'Type','Symbol'}:
                if type(event['Symbol']) is not int or not 0<=event['Symbol']<=4096:return False
                continue
            if set(event)!={'Type','ProgressPerBet'} or not isinstance(event['ProgressPerBet'],dict) or not 1<=len(event['ProgressPerBet'])<=256:return False
            keys={'RegularFreeSpinsSymbolCount','SuperFreeSpinsSymbolCount','RetriggerRegularFreeSpinsSymbolCount','RetriggerSuperFreeSpinsSymbolCount'}
            for stake,counters in event['ProgressPerBet'].items():
                if not _number(stake,positive=True) or not isinstance(counters,dict) or set(counters)!=keys or not all(type(v) is int and 0<=v<=4096 for v in counters.values()):return False
        else:return False
    for typ,indices in fev.items():
        if not isinstance(typ,str) or not typ.isdecimal() or not _ints(indices) or any(i>=len(events) or events[i]['Type']!=int(typ) for i in indices):return False
    return True
