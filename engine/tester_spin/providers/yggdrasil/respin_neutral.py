"""Neutral multiplier/respin DTO; active and unlearned states stay pending."""
from decimal import InvalidOperation
from .supermeter import num
from .named_actions import _board

def ordinary(b,constraints):
    try:
        if not isinstance(constraints,dict) or b['step']!=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency']:return False
        if num(b['betamount'])!=num(constraints['basic_amount']) or num(b['betdata']['coin'])!=num(constraints['basic_coin']) or num(b['wonamount'])!=0:return False
        ed=b['eventdata'];expected={'accC','accWa','boostData','initialPlayerState','playerState','response'}
        if set(ed)!=expected or ed['initialPlayerState']!={'d':'d'} or ed['playerState']!={'d':'d'}:return False
        boost=ed['boostData']
        if not isinstance(boost,dict) or set(boost)!={'startedRespins','reachedColossalSymbolsReel','reachedHyperMode'} or any(v is not False for v in boost.values()):return False
        response=ed['response']
        if not isinstance(response,dict) or set(response)!={'coinWin','cashWin','clientData'}:return False
        cd=response['clientData'];keys={'accC','accWa','consecutiveWins','finalBoard','multiplier','reels','reelsStripesNames','rpos','wonCoins','wonCoinsBeforeMultiplier','wonMoney','wonMoneyBeforeMultiplier','wtw'}
        if not isinstance(cd,dict) or set(cd)!=keys:return False
        if type(cd['consecutiveWins']) is not int or cd['consecutiveWins']!=0 or num(cd['multiplier'])!=1 or cd['wtw']!=[]:return False
        if any(num(cd[k])!=0 for k in ('accC','accWa','wonCoins','wonCoinsBeforeMultiplier','wonMoney','wonMoneyBeforeMultiplier')):return False
        if any(num(ed[k])!=0 for k in ('accC','accWa')) or any(num(response[k])!=0 for k in ('coinWin','cashWin')):return False
        board=cd['reels']
        if not _board(board) or len({len(col) for col in board})!=1 or cd['finalBoard']!=board:return False
        if cd['reelsStripesNames']!=['normal']*len(board):return False
        stops=cd['rpos']
        return isinstance(stops,list) and len(stops)==len(board) and all(type(v) is int and v>=0 for v in stops)
    except (KeyError,TypeError,ValueError,InvalidOperation):return False
