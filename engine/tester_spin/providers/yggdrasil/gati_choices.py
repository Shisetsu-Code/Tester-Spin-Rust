"""Gati collect role is declared by the current typed Options object."""
from decimal import Decimal,InvalidOperation
from .protocol import COMMAND

def typed_menu_present(state):
    try:cd=state['bets'][-1]['eventdata']['response']['clientData']
    except (KeyError,TypeError,IndexError):return False
    if not isinstance(cd,dict) or 'Gamble' not in cd:return False
    gamble=cd['Gamble']
    if not isinstance(gamble,dict):return True
    options=gamble.get('Options')
    # Empty typed options are the known neutral Gati outcome, not a menu.
    if set(gamble)=={'Options'} and options=={'collect':{},'riskList':[]}:return False
    return 'Options' in gamble or 'Entered' in gamble

def collect_command(state):
    try:cd=state['bets'][-1]['eventdata']['response']['clientData']
    except (KeyError,TypeError,IndexError):return None
    if not isinstance(cd,dict):return None
    gamble=cd.get('Gamble')
    if not isinstance(gamble,dict) or set(gamble)!={'Entered','Options'}:return None
    entered=gamble['Entered'];options=gamble['Options']
    if not isinstance(entered,dict) or set(entered)!={'spins'} or type(entered['spins']) is not int or entered['spins']<=0:return None
    if not isinstance(options,dict) or set(options)!={'collect','riskList'}:return None
    collect=options['collect'];risks=options['riskList']
    if not isinstance(collect,dict) or set(collect)!={'command','spins'} or collect['spins']!=entered['spins'] or type(collect['spins']) is not int:return None
    command=collect['command']
    if not isinstance(command,str) or not COMMAND.fullmatch(command) or "_COLLECT_" not in command or "_RISK_" in command:return None
    if not isinstance(risks,list) or not 0<=len(risks)<=2:return None
    domain=[command]
    for risk in risks:
        if not isinstance(risk,dict) or set(risk)!={'command','spins','chance'} or not isinstance(risk['command'],str) or not COMMAND.fullmatch(risk['command']) or type(risk['spins']) is not int or risk['spins']<=0 or isinstance(risk['chance'],bool):return None
        try:
            chance=Decimal(str(risk['chance']))
            if not chance.is_finite() or not 0<=chance<=1:return None
        except (InvalidOperation,ValueError):return None
        domain.append(risk['command'])
    if len(set(domain))!=len(domain) or set(domain)!=set(state['commands']):return None
    return command
