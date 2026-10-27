"""Stored feature quantities are not active without the explicit feature field."""
import re
from decimal import InvalidOperation
from .supermeter import num
from .named_actions import _board

def declaration(config):
    if not isinstance(config,dict):return None
    icons=config.get('Icons');height=config.get('WindowHeight')
    if not isinstance(icons,list) or not 1<=len(icons)<=256 or any(not isinstance(v,str) or not 1<=len(v)<=128 for v in icons) or len(set(icons))!=len(icons) or type(height) is not int or not 1<=height<=64:return None
    names=[k for k in config if isinstance(k,str) and re.fullmatch(r'NReel[1-9][0-9]*',k)]
    if not 1<=len(names)<=20 or set(names)!={f'NReel{i}' for i in range(1,len(names)+1)}:return None
    names=sorted(names,key=lambda k:int(k[5:]));lengths={}
    for name in names:
        strip=config[name]
        if not isinstance(strip,list) or not 1<=len(strip)<=65536 or any(type(v) is not int or not 0<=v<len(icons) for v in strip):return None
        lengths[name]=len(strip)
    return {'icons':icons,'height':height,'normal_reels':names,'strip_lengths':lengths}

def ordinary(b,constraints):
    try:
        geometry=(constraints or {}).get('saved_feature_geometry')
        if not isinstance(geometry,dict) or set(geometry)!={'icons','height','normal_reels','strip_lengths'}:return False
        if b['step']!=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency'] or num(b['betamount'])!=num(constraints['basic_amount']) or num(b['wonamount'])!=0:return False
        bd=b['betdata']
        if bd.get('cmd')!='BASE_SPIN' or num(bd['coin'])!=num(constraints['basic_coin']) or num(bd['cashBet'])!=num(constraints['basic_amount']):return False
        ed=b['eventdata'];keys={'accC','accWa','boostData','initialPlayerState','playerState','response'}
        if set(ed)!=keys or ed['boostData']!={'capsCount':0} or type(ed['boostData']['capsCount']) is not int:return False
        response=ed['response']
        if set(response)!={'coinWin','cashWin','clientData'}:return False
        cd=response['clientData'];fields={'accC','accWa','featureAfter','featureBefore','finalReels','iconsMap','reelSet','reels','reelsOrder','rpos','wonAmount','wonCoins','wts','wtw'}
        if set(cd)!=fields or cd['reelSet']!='NormalReels':return False
        before=cd['featureBefore'];after=cd['featureAfter'];names={'ExtraWilds','SecondChance','GuaranteedWin','FullLine'}
        if not isinstance(before,dict) or set(before)!=names or before!=after or ed['initialPlayerState']!=before or ed['playerState']!=after or any(type(v) is not int or not 0<=v<=1000000 for v in before.values()):return False
        if any(num(cd[k])!=0 for k in ('accC','accWa','wonAmount','wonCoins')) or any(num(ed[k])!=0 for k in ('accC','accWa')) or any(num(response[k])!=0 for k in ('coinWin','cashWin')):return False
        board=cd['reels'];width=len(geometry['normal_reels']);height=geometry['height']
        if not _board(board) or len(board)!=width or any(len(col)!=height or any(v not in geometry['icons'] for v in col) for col in board) or cd['finalReels']!=board:return False
        mapping=cd['iconsMap'];order=cd['reelsOrder'];stops=cd['rpos']
        if not isinstance(mapping,list) or any(type(v) is not int for v in mapping) or sorted(mapping)!=list(range(len(geometry['icons']))):return False
        if not isinstance(order,list) or len(order)!=width or any(not isinstance(v,str) for v in order) or set(order)!=set(geometry['normal_reels']):return False
        if not isinstance(stops,list) or len(stops)!=width or any(type(v) is not int or not 0<=v<geometry['strip_lengths'][name] for name,v in zip(order,stops)):return False
        masks=cd['wts']
        return cd['wtw']==[] and isinstance(masks,list) and len(masks)<=256 and all(isinstance(v,str) and 1<=len(v)<=4096 and set(v)=={'0'} for v in masks)
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError):return False
