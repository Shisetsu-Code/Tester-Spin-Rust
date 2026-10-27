"""Regular rounds of the numeric GameFlow SDK; money is in cents."""
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from .protocol import command_values
from .bbg_cascades import boost_data_valid

def number(v):
 if isinstance(v,bool):raise ValueError('boolean money')
 d=Decimal(str(v))
 if not d.is_finite() or d<0:raise ValueError('invalid money')
 return d

def board(v):
 return isinstance(v,list) and 1<=len(v)<=20 and all(isinstance(c,list) and 1<=len(c)<=64 and all(type(x) is int and 0<=x<=65535 for x in c) for c in v) and len({len(c) for c in v})==1

def ordinary(b,constraints):
 try:
  if not isinstance(constraints,dict) or b['step']!=1 or b['status']!='RESULTED':return False
  bd=b['betdata'];ed=b['eventdata'];rsp=ed['response'];cd=rsp['clientData']
  bdkeys={'coin','cashBet','cmd','accWa','accC'};edkeys={'accC','accWa','initialPlayerState','playerState','response'}
  if set(bd)-{'initialBalance','cmds'}!=bdkeys or set(ed)-{'boostData','nextCmds'}!=edkeys or set(rsp)!={'coinWin','cashWin','clientData'}:return False
  if set(cd)!={'Bet','Code','Completed','Round'} or type(cd['Code']) is not int or cd['Code']!=2001 or cd['Completed'] is not True:return False
  if bd['cmd']!='BASE_SPIN' or number(bd['coin'])!=number(constraints['basic_coin']) or number(bd['cashBet'])!=number(constraints['basic_amount']) or number(b['betamount'])!=number(bd['cashBet']):return False
  if 'initialBalance' in bd:number(bd['initialBalance'])
  domains=[command_values(x.get(k)) for x,k in ((bd,'cmds'),(ed,'nextCmds')) if k in x]
  if any(v not in ([],['C']) for v in domains) or (len(domains)==2 and domains[0]!=domains[1]):return False
  if 'boostData' in ed:
   boost=ed['boostData']
   if not boost_data_valid(boost):
    if not isinstance(boost,dict) or set(boost)!={'events'} or not isinstance(boost['events'],list) or len(boost['events'])>256:return False
    for item in boost['events']:
     if not isinstance(item,dict) or set(item) not in ({'Id','Type','Reset'},{'Id','Type','Collected'}) or not isinstance(item['Id'],str) or not 1<=len(item['Id'])<=128 or type(item['Type']) is not int or item['Type']!=1:return False
     if 'Reset' in item and type(item['Reset']) is not bool:return False
     if 'Collected' in item and (type(item['Collected']) is not int or not 0<=item['Collected']<=1000000):return False
  bet=cd['Bet'];rnd=cd['Round'];info=rnd['Info'];vis=rnd['VISData']
  if set(bet)!={'Lines','FeeMultiplier','Amount','GameMode','Scale','TotalBet'} or type(bet['GameMode']) is not int or bet['GameMode']!=0 or number(bet['FeeMultiplier'])!=1 or number(bet['Scale'])!=1:return False
  if type(bet['Lines']) is not int or not 1<=bet['Lines']<=4096 or number(bet['Amount'])*bet['Lines']!=number(bet['TotalBet']):return False
  cents=(number(bd['cashBet'])*100).to_integral_value(rounding=ROUND_HALF_UP)
  if number(bet['TotalBet'])!=cents:return False
  if set(rnd) not in ({'Info','VISData'},{'Info','VISData','TotalWin','SpinWin'}):return False
  if set(info)!={'RID','SRC','IDX','GameMode','RoundType','Count','Passed','Bet'} or any(type(info[k]) is not int for k in ('RID','SRC','IDX','GameMode','RoundType','Count','Passed')):return False
  if info['RID']!=1 or info['SRC']!=1 or any(info[k]!=0 for k in ('IDX','GameMode','RoundType','Count')) or info['Passed']!=1 or number(info['Bet'])!=cents:return False
  if not isinstance(ed['initialPlayerState'],dict) or not isinstance(ed['playerState'],dict):return False
  if set(vis) not in ({'Grids','Prizes','Events'},{'Grids','Prizes','Events','FEV'}):return False
  grids=vis['Grids'];events=vis['Events'];prizes=vis['Prizes']
  if not isinstance(grids,list) or not 1<=len(grids)<=64 or not all(board(g) for g in grids) or any([len(c) for c in g]!=[len(c) for c in grids[0]] for g in grids):return False
  if not isinstance(events,list) or not 1<=len(events)<=128 or not isinstance(prizes,list) or len(prizes)>4096:return False
  width=len(grids[0]);height=len(grids[0][0]);eventmap={}
  for index,event in enumerate(events):
   if not isinstance(event,dict) or type(event.get('Type')) is not int:return False
   kind=event['Type'];eventmap.setdefault(str(kind),[]).append(index)
   if kind==10:
    if set(event)!={'Type','SymbolKit','ReelStops','Grids'} or type(event['SymbolKit']) is not int or event['SymbolKit']<0:return False
    if not isinstance(event['ReelStops'],list) or len(event['ReelStops'])!=width or not all(type(v) is int and v>=0 for v in event['ReelStops']):return False
    if not isinstance(event['Grids'],list) or not event['Grids'] or not all(type(v) is int and 0<=v<len(grids) for v in event['Grids']):return False
   elif kind==20:
    if set(event)-{'Prizes','Grid'}!={'Type','Rules'}:return False
    if 'Prizes' in event:
     bounds=event['Prizes']
     if not isinstance(bounds,list) or len(bounds)!=2 or not all(type(v) is int and v>=0 for v in bounds) or bounds[0]+bounds[1]>len(prizes):return False
    if not isinstance(event['Rules'],list) or not event['Rules'] or len(set(event['Rules']))!=len(event['Rules']) or not all(type(v) is int and v>=0 for v in event['Rules']):return False
    if 'Grid' in event and (type(event['Grid']) is not int or not 0<=event['Grid']<len(grids)):return False
   elif kind==50:
    if set(event)!={'Type','SwappedSymbols','Grid'} or type(event['Grid']) is not int or not 0<=event['Grid']<len(grids):return False
    if not isinstance(event['SwappedSymbols'],list) or not all(isinstance(v,list) and len(v)==3 and all(type(x) is int for x in v) and 0<=v[1]<width and 0<=v[2]<height and grids[event['Grid']][v[1]][v[2]]==v[0] for v in event['SwappedSymbols']):return False
   elif kind==201:
    if set(event)!={'Type','StatesPerBet'} or not isinstance(event['StatesPerBet'],dict) or not event['StatesPerBet']:return False
    for value in event['StatesPerBet'].values():
     if not isinstance(value,dict) or set(value)!={'LastGrid','LastStops','SymbolKit'} or not board(value['LastGrid'])  or not isinstance(value['LastStops'],list) or len(value['LastStops'])!=width or not all(type(v) is int and v>=0 for v in value['LastStops']) or type(value['SymbolKit']) is not int or value['SymbolKit']<0:return False
   elif kind==302:
    if set(event)!={'Type','SymbolsInfo'} or not isinstance(event['SymbolsInfo'],list) or len(event['SymbolsInfo'])>width*height:return False
    for value in event['SymbolsInfo']:
     if not isinstance(value,list) or len(value)!=4 or any(number(v)<0 for v in value) or number(value[0])!=number(value[0]).to_integral_value() or number(value[0])>=width*height:return False
   else:return False
  fev=vis.get('FEV')
  if fev is not None:
   if not isinstance(fev,dict):return False
   for key,indices in fev.items():
    if key not in eventmap or indices!=eventmap[key]:return False
  won=Decimal(0)
  for prize in prizes:
   keys={'PrizeType','Value','RawValue','Rule','Combination','Length','Line','Source','Cells'}
   if not isinstance(prize,dict) or set(prize)-{'Pure'}!=keys or type(prize['PrizeType']) is not int or prize['PrizeType'] not in (10,11):return False
   if 'Pure' in prize and type(prize['Pure']) is not bool:return False
   if any(type(prize[k]) is not int or prize[k]<0 for k in ('Rule','Combination','Length','Line','Source')) or prize['Source']!=1 or not 1<=prize['Line']<=bet['Lines']:return False
   cells=prize['Cells']
   if not isinstance(cells,list) or len(cells)!=prize['Length'] or not cells or not all(isinstance(v,list) and len(v)==2 and all(type(x) is int for x in v) and 0<=v[0]<width and 0<=v[1]<height for v in cells):return False
   value=number(prize['Value']);raw=number(prize['RawValue'])
   if value!=(raw*cents if prize['PrizeType']==11 else raw):return False
   won+=value
  if number(rnd.get('TotalWin',0))!=won or number(rnd.get('SpinWin',0))!=won:return False
  cash=won/100
  if any(number(value)!=cash for value in (bd['accWa'],ed['accWa'],rsp['cashWin'])):return False
  if number(bd['accC'])!=number(ed['accC']) or number(rsp['coinWin'])!=number(ed['accC']):return False
  return number(b['wonamount']) in (Decimal(0),cash)
 except (ValueError,InvalidOperation,KeyError,TypeError,AttributeError,ArithmeticError):return False
