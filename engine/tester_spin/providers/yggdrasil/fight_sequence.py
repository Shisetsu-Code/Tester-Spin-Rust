"""Closed collection respins, with optional combats and reconciled payouts."""
from decimal import Decimal,InvalidOperation
from .supermeter import num
from .named_actions import _board
from .classic_wire import classic_win
from .collection_neutral import known_player_state

def valid_state(state,definition):
    if not isinstance(state,dict) or set(state)!={'leftHunter','rightHunter','wolfHp','userWonFreespins'} or state['userWonFreespins'] is not False:return False
    for key in ('leftHunter','rightHunter','wolfHp'):
        v=state[key]
        if not isinstance(v,dict) or set(v)!={'amount','gathered','coinsSum'}:return False
        amount=num(v['amount']);num(v['gathered']);num(v['coinsSum'])
        if key=='wolfHp':
            if not num(definition['min_hp'])<amount<=num(definition['initial_hp']):return False
        elif not 0<=amount<num(definition['max_rage']):return False
    return True

def known_sequence(bets,constraints):
    try:
        if not isinstance(bets,list) or not 3<=len(bets)<=256 or not isinstance(constraints,dict):return False
        definition=constraints['hunter_definition'];coin=num(constraints['basic_coin']);stake=num(constraints['basic_amount']);currency=constraints['currency']
        if not isinstance(definition,dict) or coin<=0 or stake<=0:return False
        total=Decimal(0);previous=None;previous_mask=None;geometry=None
        fields={'accC','accWa','beforeCollections','coinValue','collections','fights','finalBoard','freespinsAwarded','leftHunterWeapon','reelSet','reels','respinWon','rightHunterWeapon','rpos','spinName','stickyA','stickyB','stickyN','wonCoins','wonMoney','wtw'}
        for i,b in enumerate(bets):
            if b['step']!=i+1 or b['status']!='RESULTED' or b['betcurrency']!=currency or num(b['betamount'])!=(stake if i==0 else 0):return False
            ed=b['eventdata'];bd=b['betdata']
            if isinstance(bd,dict) and 'initialBalance' in bd:
                num(bd['initialBalance']);bd={k:v for k,v in bd.items() if k!='initialBalance'}
            if i==len(bets)-1:
                if set(ed)!={'exactWon'} or not isinstance(bd,dict) or set(bd)!={'coin','cashBet','cmd','accWa','accC'}:return False
                return bd['cmd']=='C' and num(bd['coin'])==coin and num(bd['cashBet'])==stake and num(bd['accC'])==total and num(bd['accWa'])==total*coin and num(ed['exactWon'])==total*coin and num(b['wonamount'])==total*coin
            final=i==len(bets)-2
            expected={'accC','accWa','response'}|({'initialPlayerState'} if i==0 else {'playerState','boostData','nextCmds'} if final else set())
            if set(ed)!=expected or num(b['wonamount'])!=0:return False
            response=ed['response']
            if not isinstance(response,dict) or set(response)!={'coinWin','cashWin','clientData'}:return False
            cd=response['clientData']
            if not isinstance(cd,dict) or set(cd)!=fields or cd['spinName']!='BaseSpin' or cd['reelSet'] not in (definition['base_reels'] if i==0 else definition['base_reels']+definition['respin_reels']) or cd['freespinsAwarded']!={} or cd['respinWon'] is not (not final):return False
            if any(type(cd[k]) is not int or cd[k]!=0 for k in ('leftHunterWeapon','rightHunterWeapon')) or num(cd['coinValue'])!=coin:return False
            before=cd['beforeCollections'];after=cd['collections']
            if not valid_state(before,definition) or not valid_state(after,definition) or (previous is not None and before!=previous):return False
            board=cd['reels']
            if not _board(board) or len({len(v) for v in board})!=1 or not _board(cd['finalBoard']) or [len(v) for v in cd['finalBoard']]!=[len(v) for v in board]:return False
            width=len(board);height=len(board[0]);cells=width*height
            if geometry is None:geometry=(width,height)
            if geometry!=(width,height):return False
            stops=cd['rpos']
            if not isinstance(stops,list) or len(stops)!=width or any(type(v) is not int or v<0 for v in stops):return False
            for k in ('stickyA','stickyB','stickyN'):
                if not isinstance(cd[k],str) or len(cd[k])!=cells or not set(cd[k])<={'0','1'}:return False
            if previous_mask is None:
                if set(cd['stickyB'])!={'0'}:return False
            elif cd['stickyB']!=previous_mask:return False
            if any(n=='1' and a!='1' for n,a in zip(cd['stickyN'],cd['stickyA'])):return False
            fights=cd['fights'];changes={'leftHunter':0,'rightHunter':0,'wolfHp':0}
            if not isinstance(fights,list) or len(fights)>cells:return False
            for fight in fights:
                if not isinstance(fight,dict) or set(fight)!={'field','rageChangeRightHunter','rageChangeLeftHunter','werewolfHpChange'}:return False
                field=fight['field']
                if not isinstance(field,dict) or set(field)!={'row','column','icon'} or any(type(field[k]) is not int for k in ('row','column')) or not 0<=field['row']<height or not 0<=field['column']<width:return False
                icon=field['icon']
                if not isinstance(icon,dict) or set(icon)!={'iconEnum','iconType'} or icon['iconType']!='NORMAL' or not isinstance(icon['iconEnum'],str) or not 1<=len(icon['iconEnum'])<=128:return False
                for key,value in [('leftHunter',fight['rageChangeLeftHunter']),('rightHunter',fight['rageChangeRightHunter']),('wolfHp',fight['werewolfHpChange'])]:
                    if type(value) is not int or (value>0 if key=='wolfHp' else value<0):return False
                    changes[key]+=value
            for key,delta in changes.items():
                if num(after[key]['amount'])!=num(before[key]['amount'])+delta or num(after[key]['gathered'])!=num(before[key]['gathered'])+abs(delta) or num(after[key]['coinsSum'])!=num(before[key]['coinsSum'])+abs(delta)*coin:return False
            wins=cd['wtw']
            if not isinstance(wins,list) or len(wins)>256 or any(not classic_win(v,cells) for v in wins):return False
            paid=sum((num(v[1]) for v in wins),Decimal(0));total+=paid
            if num(cd['wonCoins'])!=paid or num(cd['wonMoney'])!=paid*coin or any(num(o['accC'])!=total or num(o['accWa'])!=total*coin for o in (cd,ed)) or num(response['coinWin'])!=paid or num(response['cashWin'])!=paid*coin:return False
            if i==0:
                if not known_player_state(ed['initialPlayerState'],before,initial=True):return False
            if i==0 or final:
                expected_bd={'coin','cashBet','cmd','accWa','accC'}|({'cmds'} if final else set())
                if not isinstance(bd,dict) or set(bd)!=expected_bd or bd['cmd']!='BASE_SPIN' or num(bd['coin'])!=coin or num(bd['cashBet'])!=stake or num(bd['accC'])!=(total if final else 0) or num(bd['accWa'])!=(total*coin if final else 0):return False
            elif bd is not None:return False
            if final:
                boost=ed['boostData'];keys={'collectedWolfSymbols','collectedMaleHunterBonusSymbols','collectedFemaleHunterBonusSymbols','collectedMaleHunterRagePoints','collectedFemaleHunterRagePoints'}
                if ed['nextCmds']!='C' or bd['cmds']!=['C'] or not known_player_state(ed['playerState'],after) or not isinstance(boost,dict) or set(boost)!=keys or any(type(v) is not int or not 0<=v<=cells*len(bets) for v in boost.values()):return False
            previous=after;previous_mask=cd['stickyA']
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError):return False
    return False
