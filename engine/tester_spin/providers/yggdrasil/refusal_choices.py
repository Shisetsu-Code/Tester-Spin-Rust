"""SDK-declared refusal commands, bound to the current offered menu."""
import re
from .named_actions import _board

NG=re.compile(r'NG(?:GB)?_[0-9]+_[0-9]+_[0-9]+_L_[0-9]+\Z')
RISK=re.compile(r'G(?:GB)?_[0-9]+_[0-9]+_[0-9]+_L_[0-9]+\Z')
FREE=re.compile(r'FREE_SPINS_([0-9]+)_([0-9]+)\Z')
LEVEL_RISK=re.compile(r'GAMBLE_LVL_([0-9]+)_([LR])\Z')

def no_risk_choice(state):
    commands=state.get('commands')
    if not isinstance(commands,list) or not 1<=len(commands)<=3 or not all(isinstance(c,str) for c in commands) or len(set(commands))!=len(commands):return None
    bets=state.get('bets')
    if not isinstance(bets,list) or not bets:return None
    event=bets[-1].get('eventdata') or {};response=event.get('response') or {}
    cd=response.get('clientData') if isinstance(response,dict) else None
    if not isinstance(cd,dict):return None
    exits=[c for c in commands if NG.fullmatch(c)]
    if len(exits)==1 and all(NG.fullmatch(c) or RISK.fullmatch(c) for c in commands):
        chosen=exits[0]
        if any(c!=chosen[1:] for c in commands if RISK.fullmatch(c)):return None
        if set(cd)!={'gambleLevel','gambleSuccess'} or type(cd['gambleLevel']) is not int or not 0<=cd['gambleLevel']<=64 or type(cd['gambleSuccess']) is not bool:return None
        return {'cmd':chosen,'kind':'sdk_refuse_gamble','metadata':dict(cd)}
    exits=[c for c in commands if FREE.fullmatch(c)]
    if len(exits)!=1 or not all(FREE.fullmatch(c) or LEVEL_RISK.fullmatch(c) for c in commands):return None
    if set(cd)!={'initialBoard','finalBoard','gambleTriggerFrontEndData'} or not _board(cd['initialBoard']) or not _board(cd['finalBoard']) or [len(c) for c in cd['initialBoard']]!=[len(c) for c in cd['finalBoard']]:return None
    trigger=cd['gambleTriggerFrontEndData']
    keys={'currentGambleLevel','currentFreeSpinsToAward','currentBerzerksToAward'}
    if not isinstance(trigger,dict) or set(trigger)!=keys or any(type(v) is not int for v in trigger.values()):return None
    level=trigger['currentGambleLevel'];spins=trigger['currentFreeSpinsToAward'];berzerks=trigger['currentBerzerksToAward']
    if not 0<=level<=4 or not 1<=spins<=1000 or not 0<=berzerks<=64:return None
    if tuple(map(int,FREE.fullmatch(exits[0]).groups()))!=(spins,berzerks):return None
    risks=[LEVEL_RISK.fullmatch(c) for c in commands if LEVEL_RISK.fullmatch(c)]
    if risks and (level==4 or any(int(m.group(1))!=level+1 for m in risks)):return None
    return {'cmd':exits[0],'kind':'sdk_accept_awarded_spins','metadata':dict(trigger)}
