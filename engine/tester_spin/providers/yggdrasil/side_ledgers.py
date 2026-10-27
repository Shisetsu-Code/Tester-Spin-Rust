"""BASIC side-event ledgers bound to current price and explicitly inactive awards."""
import math
from decimal import Decimal
from .supermeter import num
from .named_actions import _board
from .protocol import command_values

def close(a,b):
 a=num(a);b=num(b)
 if not math.isfinite(float(a)) or not math.isfinite(float(b)):return False
 tolerance=sum((Decimal(str(math.ulp(float(v))))*4 for v in (a,b)),Decimal(0))
 return abs(a-b)<=tolerance

def valid_boards(reels):
 try:
  initial=reels['positionsHidden'];final=reels['positions']
  if not _board(initial) or not _board(final) or [len(c) for c in initial]!=[len(c) for c in final]:return False
  width=len(initial);cells=sum(map(len,initial));expected=[list(c) for c in initial];seen=set()
  hidden=reels['hidden'];scatters=reels['scatter']
  winning_positions={(p['x'],p['y']) for side in ('Left','Right') for event in reels['events'+side] for p in event['coords']}
  if not isinstance(hidden,list) or len(hidden)>cells or not isinstance(scatters,list) or len(scatters)>cells:return False
  for event in hidden:
   if not isinstance(event,dict) or set(event)!={'x','y','changeTo','multi','persistent'} or type(event['persistent']) is not bool or num(event['multi'])!=0 or not isinstance(event['changeTo'],str) or not 1<=len(event['changeTo'])<=128:return False
   x=event['x'];y=event['y']
   if type(x) is not int or type(y) is not int or not 0<=x<width or not 0<=y<len(initial[x]) or (x,y) in seen:return False
   if event['persistent'] and (x,y) not in winning_positions:return False
   seen.add((x,y));expected[x][y]=event['changeTo']
  if expected!=final:return False
  seen=set()
  for event in scatters:
   if not isinstance(event,dict) or set(event)!={'x','y','persistent'} or event['persistent'] is not False:return False
   x=event['x'];y=event['y']
   if type(x) is not int or type(y) is not int or not 0<=x<width or not 0<=y<len(final[x]) or (x,y) in seen:return False
   seen.add((x,y))
  return True
 except (KeyError,TypeError,ValueError,ArithmeticError):return False

def ordinary(b,constraints):
 try:
  if b['step']!=1 or b['status']!='RESULTED' or b['betcurrency']!=constraints['currency'] or num(b['betamount'])!=num(constraints['basic_amount']) or num(b['wonamount'])!=0:return False
  bd=b['betdata'];coin=num(constraints['basic_coin']);ed=b['eventdata']
  if coin<=0 or bd.get('cmd')!='BASE_SPIN' or num(bd['coin'])!=coin or num(bd['cashBet'])!=num(constraints['basic_amount']):return False
  fields={'accC','accWa','boostData','initialPlayerState','playerState','response'}
  if set(ed) not in (fields,fields|{'nextCmds'}) or ed['initialPlayerState']!={} or ed['playerState']!={}:return False
  boost=ed['boostData'];flags={'isWinFreeSpins','isHit8MysteryOnScreen','isHit4RespinInARow'}
  if not isinstance(boost,dict) or set(boost)!=flags or any(value is not False for value in boost.values()):return False
  response=ed['response'];cd=response['clientData']
  if set(response)!={'coinWin','cashWin','clientData'} or not isinstance(cd,dict) or set(cd)!={'rounds','winTypes','maxWinReached'} or cd['winTypes']!=[] or cd['maxWinReached'] is not False:return False
  rounds=cd['rounds']
  if not isinstance(rounds,list) or not 1<=len(rounds)<=256:return False
  total_coins=Decimal(0);total_cash=Decimal(0);retained={}
  keys={'type','eventsLeft','eventsRight','winLeft','winRight','multLeft','multRight','win','winSum','cashWin','hidden','scatter','positionsHidden','positions','maxWinReached'}
  for index,frame in enumerate(rounds,1):
   if not isinstance(frame,dict) or set(frame)!={'multiplier','index','reels'} or type(frame['index']) is not int or frame['index']!=b['step'] or num(frame['multiplier'])!=0:return False
   reels=frame['reels']
   if not isinstance(reels,dict) or set(reels)!=keys or reels['type']!=('MainGame' if index==1 else 'Respin') or reels['maxWinReached'] is not False or not valid_boards(reels):return False
   board=reels['positions']
   if not _board(board) or num(reels['multLeft'])!=1 or num(reels['multRight'])!=1:return False
   width=len(board);frame_cash=Decimal(0);frame_coins=Decimal(0)
   if index>1:
    if not retained:return False
    current_hidden={(entry['x'],entry['y']):entry['changeTo'] for entry in reels['hidden']}
    for column,values in retained.items():
     if len(values)>len(board[column]):return False
     for offset,value in enumerate(values):
      if current_hidden.get((column,len(board[column])-len(values)+offset))!=value:return False
   retained={}
   for entry in sorted(reels['hidden'],key=lambda item:(item['x'],item['y'])):
    if entry['persistent']:retained.setdefault(entry['x'],[]).append(entry['changeTo'])
   for side in ('Left','Right'):
    events=reels['events'+side];side_coins=Decimal(0)
    if not isinstance(events,list) or len(events)>256:return False
    for event in events:
     if not isinstance(event,dict) or set(event)!={'type','coords','win','winCash','id','symbol','multiplier'} or event['type']!=reels['type'] or num(event['multiplier'])!=1:return False
     if type(event['id']) is not int or not 0<=event['id']<=65536 or not isinstance(event['symbol'],str) or not 1<=len(event['symbol'])<=128:return False
     coords=event['coords'];seen=set();columns=set()
     if not isinstance(coords,list) or not 1<=len(coords)<=sum(map(len,board)):return False
     for pos in coords:
      if not isinstance(pos,dict) or set(pos)!={'x','y'} or any(type(v) is not int for v in pos.values()):return False
      x=pos['x'];y=pos['y']
      if not 0<=x<width or not 0<=y<len(board[x]) or (x,y) in seen:return False
      seen.add((x,y));columns.add(x)
     if columns!=(set(range(max(columns)+1)) if side=='Left' else set(range(min(columns),width))):return False
     won=num(event['win']);cash=num(event['winCash'])
     if won<=0 or cash<=0 or not close(cash,won*coin):return False
     side_coins+=won;frame_cash+=cash
    if num(reels['win'+side])!=side_coins:return False
    frame_coins+=side_coins
   if num(reels['win'])!=frame_coins or not close(reels['winSum'],total_cash+frame_cash) or not close(reels['cashWin'],frame_cash):return False
   total_coins+=frame_coins;total_cash+=frame_cash
  if retained:return False
  if any(num(v)!=total_coins for v in (response['coinWin'],ed['accC'],bd['accC'])) or not close(response['cashWin'],total_cash) or not close(ed['accWa'],total_cash) or not close(bd['accWa'],total_cash):return False
  if total_coins>0:return command_values(ed.get('nextCmds'))==['C'] and bd.get('cmds')==['C']
  return 'nextCmds' not in ed and not bd.get('cmds')
 except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError):return False
