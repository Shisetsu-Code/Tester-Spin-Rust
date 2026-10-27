"""Current numeric Bonus Choice from the official engine.play selector."""
import re
from .named_actions import _number
INDEX_COMMAND=re.compile(r":[1-9][0-9]{0,3}\Z")

def current_data(state):
    try:cd=state['bets'][-1]['eventdata']['response']['clientData']
    except (KeyError,TypeError,IndexError):return None
    return cd if isinstance(cd,dict) else None

def menu_present(state):
    cd=current_data(state)
    return cd is not None and type(cd.get('Code')) is int and cd['Code']==2001 and cd.get('NextRound') is not None

def pick_command(state):
    cd=current_data(state)
    if not menu_present(state):return None
    next_round=cd['NextRound']
    fields={'RID','SRC','IDX','GameMode','RoundType','Count','Passed','Bet','BGData'}
    if not isinstance(next_round,dict) or set(next_round)!=fields:return None
    if any(type(next_round[k]) is not int or next_round[k]<0 for k in fields-{'Bet','BGData'}):return None
    if next_round['GameMode']!=0 or next_round['RoundType']!=1 or next_round['Count']!=1 or next_round['Passed']!=0 or not _number(next_round['Bet'],positive=True):return None
    bet=cd.get('Bet');round_data=cd.get('Round')
    info=round_data.get('Info') if isinstance(round_data,dict) else None
    if not isinstance(bet,dict) or type(bet.get('GameMode')) is not int or bet['GameMode']!=0 or not isinstance(info,dict) or type(info.get('GameMode')) is not int or info['GameMode']!=0:return None
    bonus=next_round['BGData']
    if not isinstance(bonus,dict) or set(bonus)!={'Id','Type','IsInitialized'} or type(bonus['Id']) is not int or bonus['Id']<=0 or type(bonus['Type']) is not int or bonus['Type']!=2 or bonus['IsInitialized'] is not True:return None
    commands=state['commands']
    if not isinstance(commands,list) or not 1<=len(commands)<=256 or not all(isinstance(cmd,str) and INDEX_COMMAND.fullmatch(cmd) for cmd in commands) or len(set(commands))!=len(commands):return None
    return commands[0]
