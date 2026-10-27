"""Accept a current awarded-spin menu proved by the official SDK."""
from copy import deepcopy
from .supermeter import num
from .protocol import command_values
from .random_multiplier_base import ordinary

def accept_command(state,constraints):
 try:
  if not isinstance(constraints,dict) or constraints.get('sdk_mode_profile')!='sdk.confirmedPurchaseCards/serverPriceDomains/v1':return None
  menu=constraints.get('sdk_awarded_spin_menu')
  if not isinstance(menu,dict) or set(menu)!={'accept','risk'}:return None
  commands=state['commands']
  if not isinstance(commands,list) or len(set(commands))!=len(commands) or menu['accept'] not in commands or not set(commands)<=set(menu.values()):return None
  if state['terminal'] or len(state['bets'])!=1:return None
  bet=state['bets'][0];bd=bet['betdata'];ed=bet['eventdata'];cd=ed['response']['clientData']
  quotes=constraints['sdk_card_quotes'];quote=quotes.get(bd.get('cmd'))
  if quote is None or num(bd['coin'])!=num(quote['coin']) or num(bd['cashBet'])!=num(quote['amount']) or num(bet['betamount'])!=num(quote['amount']):return None
  factor=num(cd['fsMultiplier'])
  if factor<1 or factor!=factor.to_integral_value() or ed['boostData']['isFreeGame'] is not True:return None
  if command_values(ed['nextCmds'])!=commands or bd.get('cmds')!=commands:return None
  projected=deepcopy(bet);projected['betdata']['cmd']='BASE_SPIN'
  projected['betdata']['coin']=constraints['basic_coin']
  if num(ed['response']['cashWin'])>0:projected['eventdata']['nextCmds']='C'
  else:projected['eventdata'].pop('nextCmds')
  projected['eventdata']['boostData']['isFreeGame']=False
  projected['eventdata']['response']['clientData']['fsMultiplier']=0
  normalized={**constraints,'basic_amount':quote['amount'],'basic_coin':constraints['basic_coin']}
  return menu['accept'] if ordinary(projected,normalized) else None
 except (KeyError,ValueError,TypeError,AttributeError):return None
