"""Validate server-returned winning respins and their final zero-charge collect."""
from decimal import Decimal,InvalidOperation
from .supermeter import num
from .named_actions import _board
from .classic_wire import classic_win

def known_sequence(bets,constraints):
    try:
        if not isinstance(constraints,dict) or not isinstance(bets,list) or not 3<=len(bets)<=32:return False
        coin=num(constraints['basic_coin']);stake=num(constraints['basic_amount']);currency=constraints['currency']
        if coin<=0 or stake<=0:return False
        total=Decimal(0);wins_count=0;geometry=None;root_column=None
        for i,b in enumerate(bets):
            if b['step']!=i+1 or b['status']!='RESULTED' or b['betcurrency']!=currency or num(b['betamount'])!=(stake if i==0 else 0):return False
            ed=b['eventdata'];bd=b['betdata']
            if i==len(bets)-1:
                if ed.keys()!={'exactWon'} or not isinstance(bd,dict) or set(bd)!={'coin','cashBet','cmd','accWa','accC'}:return False
                return (bd['cmd']=='C' and num(bd['coin'])==coin and num(bd['cashBet'])==stake and num(bd['accC'])==total
                        and num(bd['accWa'])==total*coin and num(ed['exactWon'])==total*coin and num(b['wonamount'])==total*coin)
            final=i==len(bets)-2
            expected={'accC','accWa','response'}|({'initialPlayerState'} if i==0 else {'boostData','nextCmds','playerState'} if final else set())
            if not isinstance(ed,dict) or set(ed)!=expected or num(b['wonamount'])!=0:return False
            if i==0:
                if ed['initialPlayerState']!={'d':'d'} or not isinstance(bd,dict) or set(bd)!={'coin','cashBet','cmd','accWa','accC'}:return False
                if bd['cmd']!='BASE_SPIN' or num(bd['coin'])!=coin or num(bd['cashBet'])!=stake or num(bd['accC'])!=0 or num(bd['accWa'])!=0:return False
            elif not final and bd is not None:return False
            response=ed['response']
            if not isinstance(response,dict) or set(response)!={'coinWin','cashWin','clientData'}:return False
            cd=response['clientData'];keys={'accC','accWa','consecutiveWins','finalBoard','multiplier','reels','reelsStripesNames','rpos','wonCoins','wonCoinsBeforeMultiplier','wonMoney','wonMoneyBeforeMultiplier','wtw'}
            if i>0:keys|={'colossalReel','colossalReelSymbols'}
            if not final:keys|={'freeSpins','freeSpinsAwarded','reSpins'}
            if not isinstance(cd,dict) or set(cd)!=keys:return False
            board=cd['reels']
            # The client renders finalBoard directly; it can differ from strip symbols.
            final_board=cd['finalBoard']
            if not _board(board) or len({len(col) for col in board})!=1 or not _board(final_board) or [len(col) for col in final_board]!=[len(col) for col in board]:return False
            width=len(board);height=len(board[0]);cells=width*height
            if geometry is None:geometry=(width,height)
            if geometry!=(width,height):return False
            stops=cd['rpos']
            if not isinstance(stops,list) or len(stops)!=width or any(type(v) is not int or v<0 for v in stops):return False
            if i==0:
                if cd['reelsStripesNames']!=['normal']*width:return False
            else:
                block=cd['colossalReel'];symbols=cd['colossalReelSymbols']
                if not isinstance(block,dict) or set(block)!={'size','reelIndex','lastColossalReelIndex'} or not isinstance(symbols,dict) or set(symbols)!={'startRow','symbols'}:return False
                size=block['size'];start=block['reelIndex'];end=block['lastColossalReelIndex'];row=symbols['startRow'];values=symbols['symbols']
                if any(type(v) is not int for v in (size,start,end,row)) or size!=min(i+1,height) or not 0<=start<=width-size or end!=start+size-1 or not -size<row<=0:return False
                if root_column is None:root_column=start
                if root_column!=start or not isinstance(values,list) or not 1<=len(values)<=height or any(not isinstance(v,str) or not 1<=len(v)<=128 for v in values):return False
                if any((j-row)//size>=len(values) or board[col][j]!=values[(j-row)//size] for col in range(start,end+1) for j in range(height)):return False
                if cd['reelsStripesNames']!=['colossal'+str(size)+'x'+str(size) if start<=col<=end else 'normal' for col in range(width)]:return False
                if len(set(stops[start:end+1]))!=1:return False
            multiplier=num(cd['multiplier'])
            if multiplier<1:return False
            wins=cd['wtw']
            if not isinstance(wins,list) or len(wins)>256 or any(not classic_win(v,cells) or len(v)!=6 for v in wins):return False
            paid=Decimal(0);raw=Decimal(0)
            for win in wins:
                value=num(win[1]);before=num(win[4])
                if value!=before*multiplier or num(win[3])!=value*coin or num(win[5])!=before*coin:return False
                paid+=value;raw+=before
            if num(cd['wonCoins'])!=paid or num(cd['wonCoinsBeforeMultiplier'])!=raw or num(cd['wonMoney'])!=paid*coin or num(cd['wonMoneyBeforeMultiplier'])!=raw*coin:return False
            total+=paid
            if any(num(o['accC'])!=total or num(o['accWa'])!=total*coin for o in (ed,cd)):return False
            if num(response['coinWin'])!=paid or num(response['cashWin'])!=paid*coin:return False
            if paid>0:wins_count+=1
            if type(cd['consecutiveWins']) is not int or cd['consecutiveWins']!=wins_count:return False
            if final:
                boost=ed['boostData']
                if paid!=0 or ed['nextCmds']!='C' or ed['playerState']!={'d':'d'} or not isinstance(boost,dict) or set(boost)!={'startedRespins','reachedColossalSymbolsReel','reachedHyperMode'} or any(type(v) is not bool for v in boost.values()) or boost['startedRespins'] is not True:return False
                if not isinstance(bd,dict) or set(bd)!={'coin','cashBet','cmd','accWa','accC','cmds'} or bd['cmd']!='BASE_SPIN' or bd['cmds']!=['C'] or num(bd['coin'])!=coin or num(bd['cashBet'])!=stake or num(bd['accC'])!=total or num(bd['accWa'])!=total*coin:return False
            elif paid<=0 or cd['reSpins'] is not True or type(cd['freeSpins']) is not int or cd['freeSpins']!=1 or type(cd['freeSpinsAwarded']) is not int or cd['freeSpinsAwarded']!=1:return False
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError):return False
    return False
