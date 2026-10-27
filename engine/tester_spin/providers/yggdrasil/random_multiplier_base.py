"""Closed base-line outcomes with random multipliers, not a free-spin mode."""
import math
from decimal import Decimal,InvalidOperation
from .supermeter import num
from .named_actions import _board
from .protocol import command_values

def ordinary(b,constraints):
    try:
        if not isinstance(constraints,dict) or b['step']!=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency'] or num(b['betamount'])!=num(constraints['basic_amount']) or num(b['wonamount'])!=0:return False
        bd=b['betdata'];coin=num(constraints['basic_coin'])
        if coin<=0 or bd.get('cmd')!='BASE_SPIN' or num(bd['coin'])!=coin or num(bd['cashBet'])!=num(constraints['basic_amount']):return False
        ed=b['eventdata'];expected={'accC','accWa','boostData','initialPlayerState','playerState','response'}
        if set(ed) not in (expected,expected|{'nextCmds'}) or ed['initialPlayerState']!={} or ed['playerState']!={}:return False
        if 'nextCmds' in ed and command_values(ed['nextCmds'])!=['C']:return False
        boost=ed['boostData'];flags={'isFreeGame','isAchieveRandomMulti10','isHitWinCombWithWild'}
        if not isinstance(boost,dict) or set(boost)!=flags or any(type(v) is not bool for v in boost.values()) or boost['isFreeGame'] is not False:return False
        response=ed['response']
        if not isinstance(response,dict) or set(response)!={'coinWin','cashWin','clientData'}:return False
        cd=response['clientData'];keys={'board','fsMultiplier','lastRandomMultiplier','maxWinReached','multiplier','randomMultiplier','winLines','winLinesWins','winTypes'}
        if not isinstance(cd,dict) or set(cd)!=keys or num(cd['fsMultiplier'])!=0 or cd['maxWinReached'] is not False or cd['winTypes']!=[]:return False
        multipliers=[num(cd[k]) for k in ('multiplier','lastRandomMultiplier','randomMultiplier')]
        if any(v<1 or v!=v.to_integral_value() for v in multipliers) or len(set(multipliers))!=1:return False
        board=cd['board']
        if not _board(board) or len({len(v) for v in board})!=1:return False
        width=len(board);height=len(board[0]);cells=width*height
        lines=cd['winLines'];values=cd['winLinesWins']
        if not isinstance(lines,list) or not isinstance(values,list) or len(lines)!=len(values) or len(lines)>256:return False
        total=Decimal(0);tolerance=Decimal(0)
        for line,value in zip(lines,values):
            if not isinstance(line,list) or not 1<=len(line)<=cells:return False
            for position in line:
                if not isinstance(position,list) or len(position)!=2 or any(type(v) is not int for v in position) or not 0<=position[0]<width or not 0<=position[1]<height:return False
            if len({tuple(v) for v in line})!=len(line):return False
            amount=num(value);binary=float(amount)
            if amount<=0 or not math.isfinite(binary):return False
            total+=amount;tolerance+=Decimal(str(math.ulp(binary)))*4
        cash=num(response['cashWin']);coins=num(response['coinWin'])
        if not math.isfinite(float(cash)):return False
        tolerance+=Decimal(str(math.ulp(float(cash))))*4
        # JS line values can carry binary multiplication artifacts; permit only a few ULPs.
        if abs(total-cash)>tolerance or cash!=coins*coin or num(ed['accC'])!=coins or num(ed['accWa'])!=cash:return False
        return bool(lines)==(cash>0) and ('nextCmds' in ed)==(cash>0)
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError,OverflowError):return False
