"""Start an already awarded purchase using its current offered continuation command."""
import math
from copy import deepcopy
from decimal import Decimal
from .supermeter import num
from .protocol import command_values

def request(state,constraints):
 try:
  if state['terminal'] or len(state['bets'])!=1:return None
  b=state['bets'][0];bd=b['betdata'];ed=b['eventdata'];cmd=bd['cmd'];quote=constraints['purchase_quotes'].get(cmd)
  if b.get('step',0)>1:
   if not active_spin(b,constraints) or state['commands']!=[cmd]:return None
   if b['eventdata']['playerState']['freespinsRemaining']<=0:return None
   return {'cmd':cmd,'type':'bonus','amount':'0','wagerid':state['wagerid'],'step':str(state['max_step']+1),'betid':str(state['root_step'])}
  if quote is None or b['step']!=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency'] or num(b['wonamount'])!=0:return None
  if num(b['betamount'])!=num(quote['amount']) or num(bd['cashBet'])!=num(quote['amount']) or num(bd['coin'])!=num(quote['coin']):return None
  commands=state['commands']
  if not isinstance(commands,list) or len(set(commands))!=len(commands) or cmd not in commands or not set(commands)<={cmd,'GAMBLE'} or bd.get('cmds')!=commands or command_values(ed['nextCmds'])!=commands:return None
  if set(ed)!={'accC','accWa','initialPlayerState','playerState','nextCmds','response'}:return None
  keys={'freespinsRemaining','multiplier','heights','goldenBet','buyBonus','variant'}
  initial=ed['initialPlayerState'];final=ed['playerState']
  if not isinstance(initial,dict) or not isinstance(final,dict) or set(initial)!=keys or set(final)!=keys:return None
  if type(initial['freespinsRemaining']) is not int or initial['freespinsRemaining']!=0 or type(final['freespinsRemaining']) is not int or not 1<=final['freespinsRemaining']<=1000:return None
  if initial['buyBonus'] is not False or final['buyBonus'] is not True:return None
  for s in (initial,final):
   if s['goldenBet'] is not False or s['heights'] is not None or num(s['multiplier'])!=1 or type(s['variant']) is not int or not 0<=s['variant']<=4096:return None
  if initial['variant']!=final['variant']:return None
  response=ed['response']
  if not isinstance(response,dict) or set(response)!={'coinWin','cashWin','clientData'}:return None
  if any(num(v)!=0 for v in (response['coinWin'],response['cashWin'],ed['accC'],ed['accWa'],bd['accC'],bd['accWa'])):return None
  cd=response['clientData']
  if not isinstance(cd,dict) or set(cd)!={'bonusTriggered','boards','wagerId'} or cd['bonusTriggered'] is not True or not isinstance(cd['wagerId'],str) or not 1<=len(cd['wagerId'])<=4096:return None
  if not isinstance(cd['boards'],list) or len(cd['boards'])!=1:return None
  frame=cd['boards'][0];geometry=constraints['growing_ways_geometry']
  if set(frame)!={'board','total_ways','multiplier','scattersCount','winningRows'} or num(frame['multiplier'])!=1 or frame['winningRows']!=[]:return None
  board=frame['board']
  if not isinstance(board,list) or len(board)!=geometry['width'] or not all(isinstance(c,list) and all(type(v) is int and 0<=v<=4096 for v in c) for c in board):return None
  heights=list(map(len,board))
  if heights!=geometry['initial_heights'] or type(frame['total_ways']) is not int or frame['total_ways']!=math.prod(heights) or type(frame['scattersCount']) is not int or not 0<=frame['scattersCount']<=sum(heights):return None
  return {'cmd':cmd,'type':'bonus','amount':'0','wagerid':state['wagerid'],'step':str(state['max_step']+1),'betid':str(state['root_step'])}
 except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError):return None


def active_spin(b,constraints):
 try:
  from .growing_ways import ordinary
  bd=b['betdata'];ed=b['eventdata'];quote=constraints['purchase_quotes'].get(bd.get('cmd'))
  if quote is None or type(b['step']) is not int or b['step']<=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency'] or num(b['betamount'])!=0 or num(b['wonamount'])!=0:return False
  if num(bd['coin'])!=num(quote['coin']) or num(bd['cashBet'])!=num(quote['amount']):return False
  fields={'accC','accWa','initialPlayerState','playerState','response'}
  if set(ed)-{'nextCmds','boostData'}!=fields:return False
  initial=ed['initialPlayerState'];final=ed['playerState'];keys={'freespinsRemaining','multiplier','heights','goldenBet','buyBonus','variant'}
  if not isinstance(initial,dict) or not isinstance(final,dict) or set(initial)!=keys or set(final)!=keys:return False
  quantity=initial['freespinsRemaining'];left=final['freespinsRemaining']
  if type(quantity) is not int or not 1<=quantity<=1000 or type(left) is not int or left!=quantity-1 or initial['buyBonus'] is not True or type(final['buyBonus']) is not bool or left>0 and final['buyBonus'] is not True:return False
  if initial['variant']!=final['variant']:return False
  for state in (initial,final):
   mul=num(state['multiplier'])
   if mul<1 or mul>1000000 or mul!=mul.to_integral_value() or state['goldenBet'] is not False:return False
  response=ed['response'];cd=response['clientData'];frames=cd['boards']
  if cd.get('bonusTriggered') is not None or not isinstance(frames,list) or not frames:return False
  geometry=constraints['growing_ways_geometry'];first=list(map(len,frames[0]['board']));last=list(map(len,frames[-1]['board']))
  if len(first)!=geometry['width'] or first!=(initial['heights'] if initial['heights'] is not None else geometry['initial_heights']):return False
  if final['heights'] not in (None,last):return False
  previous_multiplier=num(initial['multiplier'])
  for frame in frames:
   mul=num(frame['multiplier'])
   if mul not in {previous_multiplier,previous_multiplier+1} or mul>1000000 or frame['scattersCount'] is not None:return False
   previous_multiplier=mul
  if num(final['multiplier'])!=previous_multiplier:return False
  cash=num(response['cashWin']);acc=num(ed['accWa'])
  if cash<0 or acc<cash or num(bd['accWa'])!=acc:return False
  # Reuse the strict cash/ways/coordinate validator locally. This is a free-spin
  # geometry projection, never a reclassification of the paid bonus as BASIC.
  projected=deepcopy(b);projected['step']=1;projected['betamount']=constraints['basic_amount']
  pbd=projected['betdata'];ped=projected['eventdata'];pcd=ped['response']['clientData']
  pbd.update(cmd='BASE_SPIN',coin=constraints['basic_coin'],cashBet=constraints['basic_amount'],accWa=str(cash))
  ped['accWa']=str(cash);ped.setdefault('boostData',{'easy':0,'medium':0,'hard':0})
  for state in (ped['initialPlayerState'],ped['playerState']):state.update(freespinsRemaining=0,multiplier=1,heights=None,goldenBet=False,buyBonus=False)
  pcd['bonusTriggered']=False
  for frame in pcd['boards']:frame.update(multiplier=1,scattersCount=0)
  if cash>0:ped['nextCmds']='C';pbd['cmds']=['C']
  else:ped.pop('nextCmds',None);pbd.pop('cmds',None)
  return ordinary(projected,{**constraints,'growing_ways_geometry':{'width':geometry['width'],'initial_heights':first}})
 except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError):return False


def validate_transition(before,after,chosen,constraints):
 if not isinstance(constraints,dict) or chosen.get('type')!='bonus' or chosen.get('cmd') not in constraints.get('purchase_quotes',{}):return
 prior=before['bets'][-1];generated=next(b for b in after['bets'] if b['step']==int(chosen['step']))
 if not active_spin(generated,constraints):raise ValueError('Unlearned purchased-spin outcome')
 previous=prior['eventdata'];current=generated['eventdata']
 if current['initialPlayerState']!=previous['playerState']:raise ValueError('Purchased-spin state chain changed')
 cash=num(current['response']['cashWin']);expected=num(previous['accWa'])+cash;actual=num(current['accWa'])
 tolerance=sum((Decimal(str(math.ulp(float(value))))*4 for value in (expected,actual,cash)),Decimal(0))
 if abs(expected-actual)>tolerance:raise ValueError('Purchased-spin accrued cash changed')
