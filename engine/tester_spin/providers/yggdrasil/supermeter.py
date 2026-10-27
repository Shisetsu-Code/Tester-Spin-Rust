"""Server-acknowledged loading and cashing out a classic coin accumulator."""
from decimal import Decimal,InvalidOperation
from .protocol import command_values

def num(v):
 if isinstance(v,bool):raise ValueError('boolean money')
 d=Decimal(str(v))
 if not d.is_finite() or d<0:raise ValueError('invalid money')
 return d

def profile(state):
 try:
  if state['terminal'] or not state['bets'] or any(b['status']!='RESULTED' for b in state['bets']):return None
  b=state['bets'][-1];bd=b['betdata'];ed=b['eventdata'];cmds=state['commands']
  if command_values(ed.get('nextCmds'))!=cmds:return None
  coin=num(bd['coin']);cash=num(ed['doubleAmount']);count=ed['doubleCount']
  if coin<=0 or cash<=0 or type(count) is not int or count!=1 or num(bd['nCoins'])!=1:return None
  lines=bd['lines']
  if not isinstance(lines,str) or not 1<=len(lines)<=4096 or set(lines)!={'1'}:return None
  if cmds==['LS','C']:
   keys={'accC','accWa','doubleAmount','doubleCount','nextCmds','reels','rpos','stickyA','stickyB','stickyN','wonCoins','wts','wtw'}
   if set(ed)!=keys or set(bd) not in ({'lines','coin','nCoins','cheat','clientData'},{'lines','coin','nCoins','cheat','clientData','initialBalance'}):return None
   if bd['cheat'] is not None or bd['clientData'] is not None or b['step']!=1 or num(b['betamount'])!=coin*len(lines) or num(b['wonamount'])!=0:return None
   from .classic_wire import classic_win
   board=ed['reels']
   if not isinstance(board,list) or not 1<=len(board)<=20 or not all(isinstance(col,list) and 1<=len(col)<=64 and all(isinstance(v,str) and 1<=len(v)<=128 for v in col) for col in board) or len({len(col) for col in board})!=1:return None
   cells=sum(map(len,board));positions=ed['rpos']
   if not isinstance(positions,list) or len(positions)!=len(board) or not all(type(v) is int and v>=0 for v in positions):return None
   if any(not isinstance(ed[k],str) or len(ed[k])!=cells or set(ed[k])!={'0'} for k in ('stickyA','stickyB','stickyN')):return None
   wins=ed['wtw'];wt=ed['wts']
   if not isinstance(wins,list) or not wins or len(wins)>256 or not all(classic_win(v,cells) and len(v)==3 for v in wins):return None
   if sum(num(v[1]) for v in wins)*coin!=cash:return None
   if not isinstance(wt,list) or len(wt)>256 or not all(isinstance(v,str) and 1<=len(v)<=4096 and set(v)<={'0','1'} for v in wt):return None
   if num(ed['accWa'])!=cash or num(ed['accC'])*coin!=cash or num(ed['wonCoins'])*coin!=cash:return None
   return {'cmd':'LS','cash':cash,'coin':coin,'count':count,'lines':lines}
  keys={'doubleAmount','doubleCount','doubleResult','nextCmds','supermeter'}
  bdkeys={'doubleA','doubleN','cmd','cheat','lines','coin','nCoins','variant','restoredAccumulatedWonCoin'}
  if cmds==['C','S'] and set(ed)==keys and set(bd)==bdkeys and bd['cmd']=='LS' and ed['doubleResult']=='supermeter' and bd['cheat'] is None and bd['variant'] is None and num(b['betamount'])==0 and num(b['wonamount'])==0 and num(bd['doubleA'])==cash and bd['doubleN']==count and num(bd['restoredAccumulatedWonCoin'])==0 and num(ed['supermeter'])*coin==cash:
   return {'cmd':'C','cash':cash,'coin':coin,'count':count,'lines':lines}
 except (ValueError,InvalidOperation,KeyError,TypeError,AttributeError):pass
 return None

def request(state):
 p=profile(state)
 if p is None:return None
 result={'cmd':p['cmd'],'wagerid':state['wagerid'],'step':str(state['max_step']+1),'betid':str(state['root_step'])}
 if p['cmd']=='C':result['amount']='0'
 return result

def validate(before,after,req):
 p=profile(before)
 if p is None:return False
 if req!=request(before):raise ValueError('Unexpected accumulator wire')
 if len(after['bets'])!=1 or after['max_step']!=before['max_step']+1:raise ValueError('Unexpected accumulator steps')
 b=after['bets'][0];bd=b.get('betdata') or {}
 if b['step']!=int(req['step']) or b['status']!='RESULTED' or bd.get('cmd')!=req['cmd'] or num(b['betamount'])!=0:raise ValueError('Missing zero-charge accumulator ack')
 if p['cmd']=='LS':
  q=profile(after)
  if q is None or q['cmd']!='C' or any(q[k]!=p[k] for k in ('cash','coin','count','lines')):raise ValueError('Inconsistent accumulator load')
 else:
  expected={'doubleA','doubleN','cmd','cheat','lines','coin','nCoins','variant','restoredAccumulatedWonCoin'}
  if not after['terminal'] or b.get('eventdata')!={} or set(bd)!=expected or num(b['wonamount'])!=p['cash'] or num(bd['doubleA'])!=p['cash'] or bd['doubleN']!=p['count'] or num(bd['coin'])!=p['coin'] or bd['lines']!=p['lines'] or num(bd['nCoins'])!=1 or bd['cheat'] is not None or bd['variant'] is not None or num(bd['restoredAccumulatedWonCoin'])!=0:raise ValueError('Inconsistent accumulator cash out')
  prizes=b.get('prizes')
  if not isinstance(prizes,list) or len(prizes)!=1:raise ValueError('Missing cash out prize')
  prize=prizes[0]
  if prize.get('type')!='FIXED' or prize.get('wonAspect')!='CASH' or prize.get('woncurrency')!=b['betcurrency'] or num(prize.get('wonamount'))!=p['cash'] or num(prize.get('netamount'))!=p['cash'] or prize.get('prizedata') is not None:raise ValueError('Inconsistent cash out prize')
 return True

def ordinary(b,constraints):
 try:
  if not isinstance(constraints,dict) or b['step']!=1 or b['status']!='RESULTED' or num(b['wonamount'])!=0:return False
  ed=b['eventdata'];bd=b['betdata'];keys={'accC','accWa','reels','rpos','stickyA','stickyB','stickyN','wonCoins','wts','wtw'}
  if set(ed)!=keys or set(bd) not in ({'lines','coin','nCoins','cheat','clientData'},{'lines','coin','nCoins','cheat','clientData','initialBalance'}):return False
  if any(num(ed[k])!=0 for k in ('accC','accWa','wonCoins')) or ed['wtw']!=[] or bd['cheat'] is not None or bd['clientData'] is not None:return False
  if 'initialBalance' in bd:num(bd['initialBalance'])
  lines=bd['lines'];coin=num(bd['coin'])
  if not isinstance(lines,str) or not 1<=len(lines)<=4096 or set(lines)!={'1'} or num(bd['nCoins'])!=1 or coin<=0 or coin!=num(constraints['basic_coin']) or num(b['betamount'])!=num(constraints['basic_amount']) or num(b['betamount'])!=coin*len(lines):return False
  board=ed['reels']
  if not isinstance(board,list) or not 1<=len(board)<=20 or not all(isinstance(col,list) and 1<=len(col)<=64 and all(isinstance(v,str) and 1<=len(v)<=128 for v in col) for col in board) or len({len(col) for col in board})!=1:return False
  cells=sum(map(len,board));positions=ed['rpos']
  if not isinstance(positions,list) or len(positions)!=len(board) or not all(type(v) is int and v>=0 for v in positions):return False
  if any(not isinstance(ed[k],str) or len(ed[k])!=cells or set(ed[k])!={'0'} for k in ('stickyA','stickyB','stickyN')):return False
  return isinstance(ed['wts'],list) and len(ed['wts'])<=256 and all(isinstance(v,str) and 1<=len(v)<=4096 and set(v)=={'0'} for v in ed['wts'])
 except (ValueError,InvalidOperation,KeyError,TypeError,AttributeError):return False
