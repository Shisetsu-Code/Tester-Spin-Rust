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
        if cd['featuresUsed'] not in (['spearFeature'], ['maceFeature']) or cd['reelSet']!='BaseReel':return False
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


def validate_collect(before, after, request, constraints):
    """Reconcile C against the recognized spear/mace BASIC evaluation only.

    The captured receipt repeats the cash total, coin total and original stake;
    its cash prize also reconciles when that subtree is supplied.  Older
    captured spear fixtures omit prizes, so absence is not an absence claim.
    Unrecognized evaluations remain outside this family's contract.
    """
    if len(before.get('bets', [])) != 1 or not ordinary(before['bets'][0], constraints):
        return
    try:
        root = before['bets'][0]
        if (request['cmd'] != 'C' or num(request['amount']) != 0 or
                request['wagerid'] != before['wagerid'] or before['wagerid'] != after['wagerid'] or
                int(request['step']) != root['step'] + 1 or int(request['betid']) != root['step'] or
                not after['terminal'] or len(after['bets']) != 1):
            raise ValueError('invalid receipt')
        bet = after['bets'][0]
        bd, ed = bet['betdata'], bet['eventdata']
        amount = num(root['eventdata']['response']['cashWin'])
        coins = num(root['eventdata']['response']['coinWin'])
        if (bet['step'] != root['step'] + 1 or bet['status'] != 'RESULTED' or
                num(bet['betamount']) != 0 or bet['betcurrency'] != root['betcurrency'] or
                set(bd) != {'coin', 'cashBet', 'cmd', 'accWa', 'accC'} or bd['cmd'] != 'C' or
                num(bd['coin']) != num(root['betdata']['coin']) or
                num(bd['cashBet']) != num(root['betdata']['cashBet']) or num(bd['accC']) != coins or
                set(ed) != {'exactWon'} or
                any(num(value) != amount for value in (bet['wonamount'], bd['accWa'], ed['exactWon']))):
            raise ValueError('invalid receipt')
        if 'prizes' in bet:
            prizes = bet['prizes']
            if prizes is None and amount == 0:
                return
            if not isinstance(prizes, list):
                raise ValueError('invalid cash prizes')
            paid, net = num(0), num(0)
            for prize in prizes:
                if (prize['type'] != 'FIXED' or prize['wonAspect'] != 'CASH' or
                        prize['woncurrency'] != root['betcurrency']):
                    raise ValueError('invalid cash prize')
                paid += num(prize['wonamount'])
                net += num(prize['netamount'])
            if paid != amount or net != amount:
                raise ValueError('invalid cash prize total')
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError, ArithmeticError):
        raise ValueError('Wild-replacement collect settlement mismatch') from None
