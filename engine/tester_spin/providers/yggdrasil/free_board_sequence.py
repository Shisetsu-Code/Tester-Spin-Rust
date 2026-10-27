"""Validate returned cascades, with or without an awarded free-spin counter."""
from decimal import Decimal,InvalidOperation
from .supermeter import num
from .base_game_state import ordinary_board_win

def known_sequence(bets,constraints):
    try:
        if not isinstance(bets,list) or not 3<=len(bets)<=256 or not isinstance(constraints,dict):return False
        coin=num(constraints['basic_coin']);stake=num(constraints['basic_amount']);currency=constraints['currency']
        if coin<=0 or stake<=0:return False
        total=Decimal(0);left=None;previous_respin=False;previous_multiplier=Decimal(1);shape=None;multipliers=[]
        core={'win','reels','initialBoard','finalBoard','multiplier','winPositions'}
        root_cd=bets[0]['eventdata']['response']['clientData']
        free_mode='freeSpinsAwarded' in root_cd
        if not free_mode and root_cd.get('respinAwarded') is not True:return False
        for i,b in enumerate(bets):
            if b['step']!=i+1 or b['status']!='RESULTED' or b['betcurrency']!=currency or num(b['betamount'])!=(stake if i==0 else 0):return False
            ed=b['eventdata'];bd=b['betdata']
            if isinstance(bd,dict) and 'initialBalance' in bd:
                num(bd['initialBalance'])
                bd={k:v for k,v in bd.items() if k!='initialBalance'}
            if i==len(bets)-1:
                if (free_mode and left!=0) or previous_respin or set(ed)!={'exactWon'} or not isinstance(bd,dict) or set(bd)!={'coin','cashBet','cmd','accWa','accC'}:return False
                return bd['cmd']=='C' and num(bd['coin'])==coin and num(bd['cashBet'])==stake and num(bd['accC'])==total and num(bd['accWa'])==total*coin and num(ed['exactWon'])==total*coin and num(b['wonamount'])==total*coin
            final=i==len(bets)-2
            if set(ed)!={'accC','accWa','response'}|({'boostData','nextCmds'} if final else set()) or num(b['wonamount'])!=0:return False
            response=ed['response']
            if not isinstance(response,dict) or set(response)!={'coinWin','cashWin','clientData'}:return False
            cd=response['clientData'];respin=cd.get('respinAwarded',False)
            if type(respin) is not bool:return False
            keys=core|(({'freeSpinsAwarded'} if i==0 else {'freeSpinsLeft'}) if free_mode else set())
            if respin:keys|={'respinAwarded','positionShifts','columnIndexToNewWildsNumber'}
            if set(cd)!=keys:return False
            geometry_fields=('win','reels','initialBoard','finalBoard')
            # An awarded avalanche refills the board without spinning a reel set.
            if previous_respin and cd['reels']=={'reelSetName':'NO_REEL_SET','reelStopPositions':None}:geometry_fields=('win','initialBoard','finalBoard')
            if not ordinary_board_win({k:cd[k] for k in geometry_fields}):return False
            board=cd['finalBoard'];width=len(board);height=len(board[0])
            if shape is None:shape=(width,height)
            if shape!=(width,height):return False
            def position(value):
                return isinstance(value,dict) and set(value)=={'column','row'} and type(value['column']) is int and type(value['row']) is int and 0<=value['column']<width and 0<=value['row']<height
            positions=cd['winPositions']
            if not isinstance(positions,list) or len(positions)>width*height or any(not position(v) for v in positions) or len({(v['column'],v['row']) for v in positions})!=len(positions):return False
            if respin:
                shifts=cd['positionShifts'];wilds=cd['columnIndexToNewWildsNumber']
                if not isinstance(shifts,list) or len(shifts)>width*height or any(not isinstance(v,dict) or set(v)!={'origin','target'} or not position(v['origin']) or not position(v['target']) for v in shifts):return False
                if not isinstance(wilds,dict) or len(wilds)>width or any(not isinstance(k,str) or not k.isdecimal() or str(int(k))!=k or not 0<=int(k)<width or type(v) is not int or not 1<=v<=height for k,v in wilds.items()):return False
            multiplier=num(cd['multiplier'])
            if multiplier!=previous_multiplier+int(previous_respin):return False
            if free_mode:
                if i==0:
                    left=cd['freeSpinsAwarded']
                    if type(left) is not int or not 1<=left<=256 or respin or multiplier!=1:return False
                else:
                    current=cd['freeSpinsLeft']
                    if type(current) is not int or current!=left-int(not respin) or current<0:return False
                    left=current
            elif (not final and not respin) or (i==0 and multiplier!=1):return False
            win=cd['win'];paid=Decimal(0)
            for prize in win['prizes']:
                fields={'symbol','oak','positions','coins','cash','payline','multiplier','coinsBeforeMultiplier','cashBeforeMultiplier'}
                if set(prize)!=fields or num(prize['multiplier'])!=multiplier or num(prize['coins'])!=num(prize['coinsBeforeMultiplier'])*multiplier or num(prize['cash'])!=num(prize['cashBeforeMultiplier'])*multiplier or num(prize['cash'])!=num(prize['coins'])*coin:return False
                paid+=num(prize['coins'])
            total+=paid
            if num(win['wonCoins'])!=paid or num(win['wonCash'])!=paid*coin or num(win['accumulatedWonCoins'])!=total or num(win['accumulatedWonCash'])!=total*coin or num(win['accumulatedRoundWonCoins'])!=0 or num(win['accumulatedRoundWonCash'])!=0:return False
            if num(ed['accC'])!=total or num(ed['accWa'])!=total*coin or num(response['coinWin'])!=paid or num(response['cashWin'])!=paid*coin:return False
            multipliers.append(multiplier)
            if i==0 or final:
                expected={'coin','cashBet','cmd','accWa','accC'}|({'cmds'} if final else set())
                if not isinstance(bd,dict) or set(bd)!=expected or bd['cmd']!='BASE_SPIN' or num(bd['coin'])!=coin or num(bd['cashBet'])!=stake or num(bd['accC'])!=(total if final else 0) or num(bd['accWa'])!=(total*coin if final else 0):return False
            elif bd is not None:return False
            if final:
                boost=ed['boostData']
                if (free_mode and left!=0) or respin or ed['nextCmds']!='C' or bd['cmds']!=['C'] or not isinstance(boost,dict) or set(boost)!={'boostDatas'}:return False
                items=boost['boostDatas']
                if not isinstance(items,list) or len(items)!=len(multipliers):return False
                for item,m in zip(items,multipliers):
                    if not isinstance(item,dict) or set(item)!={'numberOfWilds','multiplier'} or type(item['numberOfWilds']) is not int or not 0<=item['numberOfWilds']<=width*height or num(item['multiplier'])!=m:return False
            previous_respin=respin;previous_multiplier=multiplier
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError):return False
    return False
