"""Accept a purchased side-ledger free-spin award using the verified SDK action."""
from copy import deepcopy
import re
from .supermeter import num
from .protocol import command_values
from .side_ledgers import ordinary

def request(state,constraints):
 try:
  if constraints.get('sdk_mode_profile')!='sdk.confirmedSinglePurchaseCard/serverPriceDomains/v1':return None
  command=constraints.get('sdk_single_card_award_command')
  if not isinstance(command,str) or state['terminal'] or state['commands']!=[command] or len(state['bets'])!=1:return None
  b=state['bets'][0];bd=b['betdata'];quote=constraints['purchase_quotes'].get(bd.get('cmd'))
  if quote is None or b['step']!=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency'] or num(b['betamount'])!=num(quote['amount']) or num(bd['coin'])!=num(quote['coin']) or num(bd['cashBet'])!=num(quote['amount']):return None
  ed=b['eventdata']
  if command_values(ed['nextCmds'])!=[command] or bd.get('cmds')!=[command]:return None
  frames=ed['response']['clientData']['rounds']
  if not isinstance(frames,list) or len(frames)!=1:return None
  reels=frames[0]['reels'];award=reels['freeSpin']
  if not isinstance(award,dict) or set(award)!={'added','left','count'} or any(type(v) is not int for v in award.values()) or not 1<=award['added']<=1000 or award['left']!=0 or award['count']!=0:return None
  if not isinstance(reels['type'],str) or not re.fullmatch(r'bonusType[1-9][0-9]*',reels['type']):return None
  projected=deepcopy(b);projected['betdata']['cmd']='BASE_SPIN';projected['betdata'].pop('cmds',None);projected['eventdata'].pop('nextCmds')
  projected_reels=projected['eventdata']['response']['clientData']['rounds'][0]['reels'];projected_reels.pop('freeSpin');projected_reels['type']='MainGame'
  normalized={**constraints,'basic_amount':quote['amount'],'basic_coin':quote['coin']}
  if not ordinary(projected,normalized):return None
  if num(ed['response']['cashWin'])!=0:return None
  return {'cmd':command,'amount':'0','wagerid':state['wagerid'],'step':str(state['max_step']+1),'betid':str(state['root_step'])}
 except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError):return None
