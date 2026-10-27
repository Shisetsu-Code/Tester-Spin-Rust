"""Recognize a closed walking-symbol sequence after wire transitions validate."""
from decimal import Decimal, InvalidOperation
from .supermeter import num
from .named_actions import _board
from .classic_wire import classic_win

def known_sequence(bets,constraints):
    try:
        if not isinstance(bets,list) or not 3<=len(bets)<=32:return False
        coin=num(constraints['basic_coin']);stake=num(constraints['basic_amount'])
        if coin<=0 or stake<=0:return False
        last=bets[-1];root=bets[0];currency=root['betcurrency']
        if last['eventdata']!={} or last['betdata'].get('cmd')!='C':return False
        fields={'accC','accWa','city','reelSet','reels','rpos','sticky','stickyA','stickyB','stickyN','walkingAfter','walkingBefore','walkingNew','wonCoins','wts','wtw'}
        previous=[];total=Decimal(0);geometry=None;city=None
        for i,b in enumerate(bets):
            if b['step']!=i+1 or b['status']!='RESULTED' or b['betcurrency']!=currency or num(b['betamount'])!=(stake if i==0 else 0):return False
            if i==len(bets)-1:
                return num(b['wonamount'])==total*coin and num(b['betdata']['doubleA'])==total*coin and b['betdata']['doubleN']==1
            ed=b['eventdata'];final=i==len(bets)-2
            if set(ed)!=fields|({'doubleAmount','doubleCount','nextCmds'} if final else {'reSpins'}):return False
            if ed['reelSet']!='ReelsShiftingWild' or not isinstance(ed['city'],str) or not 1<=len(ed['city'])<=128 or not _board(ed['reels']):return False
            board=ed['reels'];width=len(board);height=len(board[0]);cells=width*height
            if len({len(col) for col in board})!=1:return False
            if geometry is None:geometry=(width,height);city=ed['city']
            if geometry!=(width,height) or city!=ed['city']:return False
            if not isinstance(ed['sticky'],str) or not 1<=len(ed['sticky'])<=128:return False
            for key in ('walkingBefore','walkingAfter','walkingNew'):
                value=ed[key]
                if not isinstance(value,list) or len(value)>cells or any(type(v) is not int or not 0<=v<cells for v in value) or len(set(value))!=len(value):return False
            before=ed['walkingBefore'];after=ed['walkingAfter'];new=ed['walkingNew']
            if before!=previous or set(after)!={v-height for v in before if v>=height}|set(new):return False
            if set(new)&{v-height for v in before if v>=height}:return False
            for key,positions in [('stickyA',after),('stickyB',before),('stickyN',new)]:
                if ed[key]!=''.join('1' if j in positions else '0' for j in range(cells)):return False
            rpos=ed['rpos']
            if not isinstance(rpos,list) or len(rpos)!=width or any(type(v) is not int or v<0 for v in rpos):return False
            wins=ed['wtw']
            if not isinstance(wins,list) or len(wins)>256 or any(not classic_win(v,cells) or len(v)!=3 for v in wins):return False
            won=num(ed['wonCoins'])
            if sum((num(v[1]) for v in wins),Decimal(0))!=won:return False
            masks=ed['wts']
            if not isinstance(masks,list) or len(masks)>256 or any(not isinstance(v,str) or not 1<=len(v)<=4096 or not set(v)<={'0','1'} for v in masks):return False
            total+=won
            if num(ed['accC'])!=total or num(ed['accWa'])!=total*coin or num(b['wonamount'])!=0:return False
            if final:
                if after or new or ed['nextCmds']!='C' or num(ed['doubleAmount'])!=total*coin or ed['doubleCount']!=1:return False
            elif ed['reSpins'] is not True or not after:return False
            previous=after
    except (KeyError,TypeError,ValueError,InvalidOperation):return False
    return False
