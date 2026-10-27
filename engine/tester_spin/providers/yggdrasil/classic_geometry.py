"""Split and synchronized reel annotations; no control or paid mode inferred."""
from math import prod
import re

def consume_geometry(ed,core):
    fields={'splitzDetail','syncedReelsDetail','winWays'}
    if not core & fields:return core
    if not fields<=core:return None
    board=ed['reels'];width=len(board);counts={str(i):len(col) for i,col in enumerate(board)}
    split=ed['splitzDetail'];sync=ed['syncedReelsDetail']
    if split is not None:
        if not isinstance(split,dict) or set(split)!={'revealedSymbol','splitzRowsIndexes','reelIndexesToRevealedRowsCounts'} or not isinstance(split['revealedSymbol'],str) or not 1<=len(split['revealedSymbol'])<=128:return None
        rows=split['splitzRowsIndexes'];mapping=split['reelIndexesToRevealedRowsCounts']
        if not isinstance(rows,list) or not rows or len(rows)>64 or any(type(v) is not int or not 0<=v<max(map(len,board)) for v in rows) or len(set(rows))!=len(rows):return None
        if not isinstance(mapping,dict) or not mapping or not set(mapping)<=set(counts):return None
        for index,count in mapping.items():
            if type(count) is not int or not counts[index]<=count<=64:return None
            counts[index]=count
    if sync is not None:
        keys={'startReelIndex','size','reelSetName','reelIndexToPickFromReelSet'}
        if not isinstance(sync,dict) or set(sync)!=keys:return None
        start,size,pick=(sync[k] for k in ('startReelIndex','size','reelIndexToPickFromReelSet'))
        if any(type(v) is not int for v in (start,size,pick)) or not 0<=start<width or not 1<=size<=width-start or not start<=pick<start+size:return None
        if not isinstance(sync['reelSetName'],str) or len(sync['reelSetName'])>128 or not re.fullmatch(r'syncedReels[1-9][0-9]*',sync['reelSetName']):return None
    if type(ed['winWays']) is not int or ed['winWays']!=prod(counts.values()):return None
    return core-fields

def neutral_level_progress(ed):
    """A base spin increments the stored counter without entering the level bonus."""
    from .named_actions import _board,_number
    from decimal import Decimal
    board=ed.get("reels")
    if not _board(board):return False
    keys={"bonusSet","coinsWon","currentLevel","currentMultiplier","gridSnapshot","lastBet","levelIncreased","mysteryWin","spinsMade","superMode","wildPattern"}
    before=ed.get("previousGameState");after=ed.get("gameState")
    for state in (before,after):
        if not isinstance(state,dict) or set(state)!=keys:return False
        if any(state[k] is not False for k in ("levelIncreased","superMode")):return False
        if type(state["lastBet"]) is not bool or not _number(state["coinsWon"]) or not _number(state["mysteryWin"]) or Decimal(str(state["mysteryWin"]))!=0:return False
        if type(state["currentLevel"]) is not int or state["currentLevel"]!=1 or type(state["currentMultiplier"]) is not int or not 1<=state["currentMultiplier"]<=100000:return False
        if type(state["bonusSet"]) is not int or not 1<=state["bonusSet"]<=64 or type(state["spinsMade"]) is not int or not 0<=state["spinsMade"]<=1000000:return False
        snapshot=state["gridSnapshot"]
        if not isinstance(snapshot,str) or len(snapshot)!=sum(map(len,board)) or not set(snapshot)<={"0","1"} or "0" not in snapshot:return False
        pattern=state["wildPattern"]
        if not isinstance(pattern,list) or not 1<=len(pattern)<=64 or not all(isinstance(pair,list) and len(pair)==2 and all(type(v) is int and -1<=v<max(len(board),max(map(len,board))) for v in pair) for pair in pattern):return False
    if after["currentMultiplier"]<before["currentMultiplier"]:return False
    if not _number(ed.get("wonCoins")) or Decimal(str(after["coinsWon"]))!=Decimal(str(before["coinsWon"]))+Decimal(str(ed["wonCoins"])):return False
    if any(a=="1" and b!="1" for a,b in zip(before["gridSnapshot"],after["gridSnapshot"])):return False
    return after["spinsMade"]==before["spinsMade"]+1 and all(after[k]==before[k] for k in keys-{"spinsMade","lastBet","coinsWon","gridSnapshot","currentMultiplier"})

def rectangular_symbol(ed):
    from .named_actions import _board
    block=ed.get("blox");board=ed.get("finalBoard")
    if not isinstance(block,dict) or set(block)!={"start","end","sym"} or not _board(board) or len({len(col) for col in board})!=1:return False
    height=len(board[0]);cells=len(board)*height
    if any(type(block[k]) is not int or not 0<=block[k]<cells for k in ("start","end")) or not isinstance(block["sym"],str) or not 1<=len(block["sym"])<=128:return False
    left,top=divmod(block["start"],height);right,bottom=divmod(block["end"],height)
    if left>right or top>bottom:return False
    return all(board[col][row]==block["sym"] for col in range(left,right+1) for row in range(top,bottom+1))

def symbol_replacement(ed):
    import re
    from .named_actions import _board
    mapping=ed.get("replaceIcons");board=ed.get("finalBoard")
    if not isinstance(mapping,dict) or not _board(board) or len({len(col) for col in board})!=1:return False
    height=len(board[0]);cells=len(board)*height
    if len(mapping)>cells:return False
    for key,value in mapping.items():
        if not isinstance(key,str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})",key) or int(key)>=cells:return False
        col,row=divmod(int(key),height)
        if not isinstance(value,str) or not 1<=len(value)<=128 or board[col][row]!=value:return False
    return True

def split_field_geometry(ed):
    from .named_actions import _board
    fields=ed.get('splitFields');board=ed.get('finalBoard')
    if not isinstance(fields,list) or len(fields)>1280 or not _board(board):return False
    known={v for col in board for v in col};seen=set()
    for item in fields:
        if not isinstance(item,dict) or set(item)!={'position','symbol','symbolsCount','column','row'}:return False
        pos=item['position']
        if not isinstance(pos,dict) or set(pos)!={'row','column'} or any(type(v) is not int for v in pos.values()):return False
        col=pos['column'];row=pos['row']
        if any(type(item[k]) is not int for k in ('column','row')) or item['column']!=col or item['row']!=row or not 0<=col<len(board) or not 0<=row<len(board[col]):return False
        if (col,row) in seen or type(item['symbolsCount']) is not int or not 1<=item['symbolsCount']<=64:return False
        seen.add((col,row))
        symbol=item['symbol']
        if not isinstance(symbol,str) or symbol not in known or (board[col][row]!=symbol and board[col][row]!='MYSTERY'):return False
    return True


def neutral_jackpot_features(ed):
    from .named_actions import _number
    from decimal import Decimal
    data=ed.get('spinData')
    if not isinstance(data,dict) or set(data)!={'featuresData','bonusWon','jackpotStatusBefore','jackpotStatusAfter'} or data['featuresData']!={}:return False
    bonus=data['bonusWon']
    if not isinstance(bonus,dict) or set(bonus)!={'coins','cash'} or any(not _number(v) or Decimal(str(v))!=0 for v in bonus.values()):return False
    before=data['jackpotStatusBefore'];after=data['jackpotStatusAfter']
    if not isinstance(before,dict) or not 1<=len(before)<=64 or not isinstance(after,dict) or before!=after:return False
    return all(isinstance(k,str) and 1<=len(k)<=128 and _number(v,positive=True) for k,v in before.items())
