"""Gati BASIC event packets, with no remaining spins or gamble branch."""
from decimal import Decimal
from .named_actions import _number

def _zero(v):return _number(v) and Decimal(str(v))==0

def _panel(panel):
    if not isinstance(panel,dict) or set(panel)!={'reels','reelList','symbolsAbove','symbolsBelow'} or type(panel['reels']) is not int or not 1<=panel['reels']<=20:return None
    width=panel['reels'];heights=[]
    for key in ('reelList','symbolsAbove','symbolsBelow'):
        reels=panel[key]
        if not isinstance(reels,list) or len(reels)!=width:return None
        for reel in reels:
            if not isinstance(reel,dict) or set(reel)!={'symbols'} or not isinstance(reel['symbols'],list) or not 1<=len(reel['symbols'])<=64:return None
            if not all(isinstance(sym,dict) and set(sym)=={'value'} and type(sym['value']) is int and 0<=sym['value']<=4096 for sym in reel['symbols']):return None
            if key=='reelList':heights.append(len(reel['symbols']))
    return heights

def _wins(event,heights):
    if not isinstance(event,dict) or set(event)!={'totalLineWinnings','totalLineWinningsNonMultiplied','winningLines'} or not all(_number(event[k]) for k in ('totalLineWinnings','totalLineWinningsNonMultiplied')):return False
    lines=event['winningLines']
    if not isinstance(lines,list) or len(lines)>256:return False
    for line in lines:
        if not isinstance(line,dict) or set(line)!={'winAmount','multiplier','occurrences','winningLine','positions','symbol'} or not _number(line['winAmount']) or not _number(line['multiplier'],positive=True):return False
        if type(line['occurrences']) is not int or not 1<=line['occurrences']<=len(heights) or type(line['winningLine']) is not int or not 0<=line['winningLine']<4096:return False
        positions=line['positions'];symbol=line['symbol']
        if not isinstance(positions,list) or not 1<=len(positions)<=1280:return False
        for pos in positions:
            if not isinstance(pos,dict) or set(pos)!={'reel','row'} or type(pos['reel']) is not int or type(pos['row']) is not int or not 0<=pos['reel']<len(heights) or not 0<=pos['row']<heights[pos['reel']]:return False
        if not isinstance(symbol,dict) or set(symbol)!={'value','ids'} or type(symbol['value']) is not int or not 0<=symbol['value']<=4096 or not isinstance(symbol['ids'],list) or len(symbol['ids'])>1280 or not all(type(v) is int and 0<=v<=4096 for v in symbol['ids']):return False
    return True

def ordinary_gati(cd):
    core={'ResultId','ResultTime','Mode','Spin'}
    if not isinstance(cd,dict) or set(cd) not in (core,core|{'Gamble','FinalGameState'}) or cd['Mode']!='BASIC' or not all(isinstance(cd[k],str) and 1<=len(cd[k])<=128 for k in ('ResultId','ResultTime')):return False
    if 'Gamble' in cd:
        if cd['Gamble']!={'Options':{'collect':{},'riskList':[]}}:return False
        state=cd['FinalGameState']
        fields={'inProgress','winAmount','collectionCash','collectionCount','collectionMeters','collectionMetersActive'}
        if not isinstance(state,dict) or set(state)!=fields or state['inProgress'] is not False or not _number(state['winAmount']):return False
        arrays=[state[k] for k in ('collectionCash','collectionCount','collectionMeters','collectionMetersActive')]
        if not all(isinstance(v,list) and 1<=len(v)<=256 for v in arrays) or len({len(v) for v in arrays})!=1:return False
        if not all(_number(v) for v in state['collectionCash']) or not all(type(v) is int and v>=0 for v in state['collectionCount']+state['collectionMeters']) or not all(v is False for v in state['collectionMetersActive']):return False
    spins=cd['Spin']
    if not isinstance(spins,list) or not 1<=len(spins)<=256:return False
    core={'lines','spinsRemainingTotal','spinsRemainingPlayerView','cashWinSoFar','totalWinnings','reelSetName','resultsPanel','blockSizes','addedWilds','scatterCount','additionalSpinsAwarded'}
    gong={'initialGongMultiplier','gongReelMultipliers','finalGongMultiplier'}
    collection={'initialCollectionMeters','initialCollectionMetersActive','collectionMultiplier','finalCollectionMeters','finalCollectionMetersActive'}
    for spin in spins:
        if not isinstance(spin,dict) or set(spin)!={'spinEvent','winningLinesEvent'}:return False
        event=spin['spinEvent']
        if not isinstance(event,dict) or set(event) not in (core|gong,core|collection):return False
        if not all(_zero(event[k]) for k in ('spinsRemainingTotal','spinsRemainingPlayerView','additionalSpinsAwarded')) or event['reelSetName'] is not None or event['addedWilds']!=[]:return False
        if type(event['lines']) is not int or not 1<=event['lines']<=4096 or type(event['scatterCount']) is not int or event['scatterCount']<0 or not all(_number(event[k]) for k in ('cashWinSoFar','totalWinnings')):return False
        heights=_panel(event['resultsPanel'])
        if heights is None:return False
        blocks=event['blockSizes']
        if not isinstance(blocks,list) or not blocks or not all(type(v) is int and 1<=v<=len(heights) for v in blocks) or sum(blocks)!=len(heights):return False
        if set(event)==core|gong:
            multipliers=event['gongReelMultipliers']
            if not all(_number(event[k],positive=True) for k in ('initialGongMultiplier','finalGongMultiplier')) or not isinstance(multipliers,list) or len(multipliers)!=len(heights) or not all(_number(v) for v in multipliers):return False
        else:
            if not _number(event['collectionMultiplier'],positive=True):return False
            arrays=[event[k] for k in collection if k!='collectionMultiplier']
            if not all(isinstance(v,list) and 1<=len(v)<=256 for v in arrays) or len({len(v) for v in arrays})!=1:return False
            if not all(type(v) is int and v>=0 for k in ('initialCollectionMeters','finalCollectionMeters') for v in event[k]) or not all(v is False for k in ('initialCollectionMetersActive','finalCollectionMetersActive') for v in event[k]):return False
        if not _wins(spin['winningLinesEvent'],heights):return False
    return True
