"""Neutral hunter/health collections bounded by current server configuration."""
import re
from decimal import InvalidOperation
from .supermeter import num
from .named_actions import _board

def declaration(config):
    try:
        if not isinstance(config,dict):return None
        types=config['SpinTypes'];rage=num(config['MaximumRage']);low=num(config['MinimumWolfHp']);high=num(config['InitialWolfHp'])
        if not isinstance(types,list) or not types or types[0]!='BaseSpin' or any(not isinstance(v,str) or not v for v in types) or len(set(types))!=len(types) or rage<=0 or high<=low:return None
        reels={k:v for k,v in config.items() if isinstance(k,str) and re.fullmatch(r'BaseReels[1-9][0-9]*',k)}
        if not 1<=len(reels)<=64:return None
        respin_reels={k:v for k,v in config.items() if isinstance(k,str) and re.fullmatch(r'RespinReels[1-9][0-9]*(?:NoScatters)?',k)}
        if len(respin_reels)>64:return None
        for strips in list(reels.values())+list(respin_reels.values()):
            if not isinstance(strips,list) or not 1<=len(strips)<=20 or any(not isinstance(col,list) or not 1<=len(col)<=65536 or any(not isinstance(v,str) or not 1<=len(v)<=128 for v in col) for col in strips):return None
        return {'max_rage':str(rage),'min_hp':str(low),'initial_hp':str(high),'base_reels':list(reels),'respin_reels':list(respin_reels)}
    except (KeyError,TypeError,ValueError,InvalidOperation):return None

def neutral_fights(fights,board):
    if not _board(board) or not isinstance(fights,list) or len(fights)>sum(map(len,board)):return False
    for fight in fights:
        if not isinstance(fight,dict) or set(fight)!={'field','rageChangeLeftHunter','rageChangeRightHunter','werewolfHpChange'}:return False
        if any(type(fight[k]) is not int or fight[k]!=0 for k in ('rageChangeLeftHunter','rageChangeRightHunter','werewolfHpChange')):return False
        field=fight['field']
        if not isinstance(field,dict) or set(field)!={'row','column','icon'} or type(field['row']) is not int or type(field['column']) is not int or not 0<=field['column']<len(board) or not 0<=field['row']<len(board[field['column']]):return False
        icon=field['icon']
        if not isinstance(icon,dict) or set(icon)!={'iconEnum','iconType'} or icon['iconType']!='NORMAL' or not isinstance(icon['iconEnum'],str) or not 1<=len(icon['iconEnum'])<=128:return False
    return True

def known_player_state(state,collections,*,initial=False):
    return (isinstance(state,dict) and set(state)=={'collections','newUser'}
            and state['collections']==collections and type(state['newUser']) is bool
            and (initial or state['newUser'] is False))

def ordinary(b,constraints):
    try:
        definition=(constraints or {}).get('hunter_definition')
        if not isinstance(definition,dict) or set(definition)!={'max_rage','min_hp','initial_hp','base_reels','respin_reels'}:return False
        if b['step']!=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency'] or num(b['betamount'])!=num(constraints['basic_amount']) or num(b['wonamount'])!=0:return False
        bd=b['betdata']
        if bd.get('cmd')!='BASE_SPIN' or num(bd['coin'])!=num(constraints['basic_coin']) or num(bd['cashBet'])!=num(constraints['basic_amount']):return False
        ed=b['eventdata'];keys={'accC','accWa','boostData','initialPlayerState','playerState','response'}
        if set(ed)!=keys:return False
        boost=ed['boostData'];boost_keys={'collectedWolfSymbols','collectedMaleHunterBonusSymbols','collectedFemaleHunterBonusSymbols','collectedMaleHunterRagePoints','collectedFemaleHunterRagePoints'}
        if not isinstance(boost,dict) or set(boost)!=boost_keys or any(type(v) is not int or not 0<=v<=1280 for v in boost.values()):return False
        if any(boost[k]!=0 for k in ('collectedMaleHunterRagePoints','collectedFemaleHunterRagePoints')):return False
        response=ed['response']
        if set(response)!={'coinWin','cashWin','clientData'}:return False
        cd=response['clientData'];fields={'accC','accWa','beforeCollections','coinValue','collections','fights','finalBoard','freespinsAwarded','leftHunterWeapon','reelSet','reels','respinWon','rightHunterWeapon','rpos','spinName','stickyA','stickyB','stickyN','wonCoins','wonMoney','wtw'}
        if set(cd)!=fields or cd['spinName']!='BaseSpin' or cd['reelSet'] not in definition['base_reels'] or cd['respinWon'] is not False or not neutral_fights(cd['fights'],cd['reels']) or cd['freespinsAwarded']!={}:return False
        if any(type(cd[k]) is not int or cd[k]!=0 for k in ('leftHunterWeapon','rightHunterWeapon')):return False
        state=cd['collections']
        if not isinstance(state,dict) or set(state)!={'leftHunter','rightHunter','wolfHp','userWonFreespins'} or state['userWonFreespins'] is not False or state!=cd['beforeCollections']:return False
        for k in ('leftHunter','rightHunter','wolfHp'):
            v=state[k]
            if not isinstance(v,dict) or set(v)!={'amount','gathered','coinsSum'} or num(v['gathered'])!=0 or num(v['coinsSum'])!=0:return False
            amount=num(v['amount'])
            if k=='wolfHp':
                if not num(definition['min_hp'])<amount<=num(definition['initial_hp']):return False
            elif not 0<=amount<num(definition['max_rage']):return False
        if not known_player_state(ed['initialPlayerState'],state,initial=True) or not known_player_state(ed['playerState'],state):return False
        if num(cd['coinValue'])!=num(constraints['basic_coin']) or cd['wtw']!=[] or any(num(cd[k])!=0 for k in ('accC','accWa','wonCoins','wonMoney')) or any(num(ed[k])!=0 for k in ('accC','accWa')) or any(num(response[k])!=0 for k in ('coinWin','cashWin')):return False
        board=cd['reels']
        if not _board(board) or len({len(v) for v in board})!=1 or cd['finalBoard']!=board:return False
        cells=sum(map(len,board))
        if any(boost[k]>cells for k in ('collectedWolfSymbols','collectedMaleHunterBonusSymbols','collectedFemaleHunterBonusSymbols')):return False
        if any(not isinstance(cd[k],str) or len(cd[k])!=cells or set(cd[k])!={'0'} for k in ('stickyA','stickyB','stickyN')):return False
        positions=cd['rpos']
        return isinstance(positions,list) and len(positions)==len(board) and all(type(v) is int and v>=0 for v in positions)
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError):return False
