"""Current BASIC line evaluation with explicit, non-bonus wild replacements."""
from decimal import InvalidOperation
from .supermeter import num
from .named_actions import _board
from .protocol import command_values
from .classic_wire import ordinary_flat_event


def ordinary(bet, constraints):
    try:
        if not isinstance(constraints,dict) or bet['step']!=1 or bet['status']!='RESULTED':return False
        if bet['betcurrency']!=constraints['currency'] or num(bet['betamount'])!=num(constraints['basic_amount']) or num(bet['wonamount'])!=0:return False
        bd=bet['betdata'];ed=bet['eventdata'];coin=num(constraints['basic_coin'])
        if coin<=0 or bd['cmd']!='BASE_SPIN' or num(bd['coin'])!=coin or num(bd['cashBet'])!=num(constraints['basic_amount']):return False
        keys={'accC','accWa','boostData','response'}
        if not keys<=set(ed)<=keys|{'nextCmds'} or command_values(ed.get('nextCmds')) not in ([],['C']):return False
        boost=ed['boostData'];flags={'gotScatter2OrMore','gotScatter3AndEnteredFreespins','gotScatter3AndWonDeathmatch'}
        if not isinstance(boost,dict) or set(boost)!=flags or any(type(v) is not bool for v in boost.values()):return False
        if boost['gotScatter3AndEnteredFreespins'] or boost['gotScatter3AndWonDeathmatch']:return False
        response=ed['response'];cd=response['clientData']
        core={'accC','accWa','featuresUsed','finalBoard','reelSet','reels','rpos','scatterWonExtraCoins','scatterWonExtraMoney','wonCoins','wonMoney','wtw'}
        if set(response)!={'coinWin','cashWin','clientData'} or not isinstance(cd,dict) or set(cd)!=core|{'wildsAwarded'}:return False
        if cd['featuresUsed']!=['spearFeature'] or cd['reelSet']!='BaseReel':return False
        before=cd['reels'];after=cd['finalBoard'];awards=cd['wildsAwarded']
        if not _board(before) or not _board(after) or list(map(len,before))!=list(map(len,after)) or not isinstance(awards,list) or not 1<=len(awards)<=sum(map(len,before)):return False
        changed=set()
        for award in awards:
            if not isinstance(award,dict) or set(award)!={'row','column','icon'}:return False
            x,y=award['column'],award['row'];icon=award['icon']
            if type(x) is not int or type(y) is not int or not 0<=x<len(before) or not 0<=y<len(before[x]) or (x,y) in changed:return False
            if icon!={'iconEnum':before[x][y],'iconType':'NORMAL'} or after[x][y]!='Wild':return False
            changed.add((x,y))
        if any(after[x][y]!=before[x][y] for x,col in enumerate(before) for y in range(len(col)) if (x,y) not in changed):return False
        normalized={k:v for k,v in cd.items() if k!='wildsAwarded'}
        normalized['featuresUsed']=['noFeature']
        if not ordinary_flat_event(normalized,constraints):return False
        coins=num(cd['wonCoins']);cash=coins*coin
        if any(num(value)!=coins for value in (bd['accC'],ed['accC'],response['coinWin'],cd['accC'])):return False
        if any(num(value)!=cash for value in (bd['accWa'],ed['accWa'],response['cashWin'],cd['accWa'],cd['wonMoney'])):return False
        return (sum((num(win[1]) for win in cd['wtw']),num(0))==coins
                and num(cd['scatterWonExtraCoins'])==0 and num(cd['scatterWonExtraMoney'])==0)
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError,IndexError):return False
