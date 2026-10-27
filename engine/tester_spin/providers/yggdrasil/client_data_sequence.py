"""Explicit BASE client-data sequences with no awarded free-spin/collection mode."""
from decimal import Decimal
from .named_actions import _board,_number

def ordinary_sequence(cd):
    if not isinstance(cd,dict) or set(cd)!={'clientDatas'}:return False
    items=cd['clientDatas']
    if not isinstance(items,list) or not 1<=len(items)<=256:return False
    fields={'win','reels','initialBoard','finalBoard','freeSpinsAwarded','spinType','ragnarokWon','ragnarokFreeSpinsAwarded','finishedCollections','collectedSymbols','freeSpinsWon'}
    money={'wonCoins','wonCash','accumulatedWonCoins','accumulatedWonCash','accumulatedRoundWonCoins','accumulatedRoundWonCash'}
    for item in items:
        if not isinstance(item,dict) or set(item)!=fields or item['spinType']!='BASE':return False
        if any(item[k] is not False for k in ('ragnarokWon','freeSpinsWon')) or any(type(item[k]) is not int or item[k]!=0 for k in ('freeSpinsAwarded','ragnarokFreeSpinsAwarded')) or item['finishedCollections']!=[] or item['collectedSymbols']!={}:return False
        if not _board(item['initialBoard']) or not _board(item['finalBoard']) or [len(c) for c in item['initialBoard']]!=[len(c) for c in item['finalBoard']]:return False
        board=item['finalBoard'];reels=item['reels']
        if not isinstance(reels,dict) or set(reels)!={'reelSetName','reelStopPositions'} or not isinstance(reels['reelSetName'],str) or not 1<=len(reels['reelSetName'])<=128:return False
        stops=reels['reelStopPositions']
        if not isinstance(stops,list) or len(stops)!=len(board) or not all(type(s) is int and s>=0 for s in stops):return False
        win=item['win']
        if not isinstance(win,dict) or set(win)!=money|{'prizes'} or not all(_number(win[k]) for k in money):return False
        prizes=win['prizes']
        if not isinstance(prizes,list) or len(prizes)>256:return False
        for prize in prizes:
            if not isinstance(prize,dict) or set(prize)!={'symbol','oak','positions','coins','cash','ways'}:return False
            if not isinstance(prize['symbol'],str) or not 1<=len(prize['symbol'])<=128 or any(type(prize[k]) is not int or prize[k]<=0 for k in ('oak','ways')) or not all(_number(prize[k]) for k in ('coins','cash')):return False
            positions=prize['positions']
            if not isinstance(positions,list) or not 1<=len(positions)<=1280:return False
            for pos in positions:
                if not isinstance(pos,dict) or set(pos)!={'x','y'} or any(type(pos[k]) is not int for k in pos) or not 0<=pos['x']<len(board) or not 0<=pos['y']<len(board[pos['x']]):return False
        if sum((Decimal(str(p['coins'])) for p in prizes),Decimal(0))!=Decimal(str(win['wonCoins'])) or sum((Decimal(str(p['cash'])) for p in prizes),Decimal(0))!=Decimal(str(win['wonCash'])):return False
    return True


def known_awarded_sequence(cd):
    """Known paid BASE trigger for candidate selection, never return-to-base proof."""
    from copy import deepcopy
    if not isinstance(cd,dict) or set(cd)!={'clientDatas'} or not isinstance(cd['clientDatas'],list) or not 1<=len(cd['clientDatas'])<=256:return False
    normalized=deepcopy(cd);awarded=False
    for item in normalized['clientDatas']:
        if not isinstance(item,dict):return False
        count=item.get('freeSpinsAwarded');flag=item.get('freeSpinsWon')
        if type(count) is not int or count<0 or type(flag) is not bool or flag!=(count>0):return False
        awarded=awarded or flag
        item['freeSpinsAwarded']=0;item['freeSpinsWon']=False
    return awarded and ordinary_sequence(normalized)
