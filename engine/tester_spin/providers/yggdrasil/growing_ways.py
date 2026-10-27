"""Ordinary cash cascades with explicitly inactive bonus state and growing columns."""
import math
from decimal import Decimal
from .supermeter import num
from .protocol import command_values

def declaration(props):
 config=props.get('Config')
 board=config.get('initialBoard') if isinstance(config,dict) else None
 if not isinstance(board,list) or not 1<=len(board)<=20:return None
 if not all(isinstance(col,list) and 1<=len(col)<=64 and all(type(v) is int and 0<=v<=4096 for v in col) for col in board):return None
 return {'width':len(board),'initial_heights':[len(col) for col in board]}

def ordinary(b,constraints):
 try:
  geometry=constraints['growing_ways_geometry'];width=geometry['width']
  if b['step']!=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency'] or num(b['betamount'])!=num(constraints['basic_amount']) or num(b['wonamount'])!=0:return False
  bd=b['betdata'];ed=b['eventdata']
  if bd.get('cmd')!='BASE_SPIN' or num(bd['coin'])!=num(constraints['basic_coin']) or num(bd['cashBet'])!=num(constraints['basic_amount']):return False
  fields={'accC','accWa','boostData','initialPlayerState','playerState','response'}
  if set(ed) not in (fields,fields|{'nextCmds'}):return False
  state_keys={'freespinsRemaining','multiplier','heights','goldenBet','buyBonus','variant'}
  for state in (ed['initialPlayerState'],ed['playerState']):
   if not isinstance(state,dict) or set(state)!=state_keys or type(state['freespinsRemaining']) is not int or state['freespinsRemaining']!=0 or num(state['multiplier'])<1 or num(state['multiplier'])>1000000 or num(state['multiplier'])!=num(state['multiplier']).to_integral_value() or type(state['goldenBet']) is not bool or type(state['buyBonus']) is not bool or type(state['variant']) is not int or not 0<=state['variant']<=4096:return False
  initial=ed['initialPlayerState'];final=ed['playerState']
  if final['goldenBet'] is not False or final['buyBonus'] is not False:return False
  clearing_prior_mode=initial['buyBonus'] or initial['goldenBet']
  old_heights=initial['heights']
  if old_heights is not None and (not isinstance(old_heights,list) or len(old_heights)!=width or any(type(v) is not int or not 1<=v<=64 for v in old_heights)):return False
  if final['heights'] is not None or num(final['multiplier'])!=1:return False
  if not clearing_prior_mode and (initial['variant']!=final['variant'] or num(initial['multiplier'])!=1 or old_heights not in (None,geometry['initial_heights'])):return False
  boost=ed['boostData']
  if not isinstance(boost,dict) or set(boost)!={'easy','medium','hard'} or any(type(v) is not int or not 0<=v<=256 for v in boost.values()):return False
  response=ed['response']
  if set(response)!={'coinWin','cashWin','clientData'} or num(response['coinWin'])!=0 or num(ed['accC'])!=0 or num(bd['accC'])!=0:return False
  cd=response['clientData']
  if not isinstance(cd,dict) or set(cd)!={'bonusTriggered','boards','wagerId'} or cd['bonusTriggered'] is not False or not isinstance(cd['wagerId'],str) or not 1<=len(cd['wagerId'])<=4096:return False
  frames=cd['boards']
  if not isinstance(frames,list) or not 1<=len(frames)<=256:return False
  total=Decimal(0);tolerance=Decimal(0);previous=None;previous_multiplier=None
  for i,frame in enumerate(frames):
   if not isinstance(frame,dict) or set(frame)!={'board','total_ways','multiplier','scattersCount','winningRows'}:return False
   multiplier=num(frame['multiplier'])
   if multiplier<1 or multiplier>1000000 or multiplier!=multiplier.to_integral_value() or previous_multiplier is not None and multiplier not in {previous_multiplier,previous_multiplier+1}:return False
   previous_multiplier=multiplier
   board=frame['board']
   if not isinstance(board,list) or len(board)!=width or not all(isinstance(col,list) and 1<=len(col)<=64 and all(type(v) is int and 0<=v<=4096 for v in col) for col in board):return False
   heights=list(map(len,board));cells=sum(heights)
   if previous is None:
    if heights!=geometry['initial_heights']:return False
   elif board[1:]!=previous[:-1] or len(board[0]) not in {len(previous[0]),len(previous[0])+1}:return False
   if type(frame['total_ways']) is not int or frame['total_ways']!=math.prod(heights) or type(frame['scattersCount']) is not int or not 0<=frame['scattersCount']<=cells:return False
   wins=frame['winningRows']
   if not isinstance(wins,list) or len(wins)>256 or bool(wins)!=(i<len(frames)-1):return False
   # Server-provided positions can include substitutes, as in the SDK row mapper.
   for win in wins:
    if not isinstance(win,dict) or set(win)!={'symbol','payout','winningWays','positions'} or type(win['symbol']) is not int:return False
    positions=win['positions'];columns={};seen=set()
    if not isinstance(positions,list) or not 1<=len(positions)<=cells:return False
    for pos in positions:
     if not isinstance(pos,dict) or set(pos)!={'reel','row'} or any(type(v) is not int for v in pos.values()):return False
     col=pos['reel'];row=pos['row']
     if not 0<=col<width or not 0<=row<heights[col] or (col,row) in seen:return False
     seen.add((col,row));columns[col]=columns.get(col,0)+1
    if sorted(columns)!=list(range(len(columns))) or type(win['winningWays']) is not int or win['winningWays']!=math.prod(columns.values()):return False
    amount=num(win['payout']);binary=float(amount)
    if amount<=0 or not math.isfinite(binary):return False
    total+=amount;tolerance+=Decimal(str(math.ulp(binary)))*4
   previous=board
  cash=num(response['cashWin'])
  if cash<0 or not math.isfinite(float(cash)) or num(ed['accWa'])!=cash or num(bd['accWa'])!=cash:return False
  tolerance+=Decimal(str(math.ulp(float(cash))))*4
  if abs(total-cash)>tolerance:return False
  if cash>0:return command_values(ed.get('nextCmds'))==['C'] and bd.get('cmds')==['C']
  return 'nextCmds' not in ed and not bd.get('cmds')
 except (KeyError,ValueError,TypeError,AttributeError,ArithmeticError):return False
