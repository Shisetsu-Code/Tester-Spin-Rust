"""Declaration-bound ordinary state for the portal/variable-ways SDK."""
from .round_outcomes import number
from .classic_wire import classic_win
from .protocol import command_values
FIELDS={'FreeSpinsBase','ExtraWilds','WindowHeight','NonPortalReelHeight','CoinsPerBetNormal'}
def declaration(config):
 if not isinstance(config,dict) or not FIELDS<=set(config):return None
 values={k:config[k] for k in FIELDS}
 return values if all(type(v) is int and 0<v<=1000000 for v in values.values()) else None

def neutral(s,width,definition,stake):
 keys={'collectionGathered','reelsName','portalSpinsAwarded','portalReels','reelsPositions','previousReelsPositions','reels','previousReels','portalSpinsLeft','stateChanges','numberOfLines','betAmount','coinsPerBet','pickAndClickResult','lastChangeOfWinWays'}
 if not isinstance(s,dict) or set(s)!=keys:return False
 if s['collectionGathered']!={} or s['reelsName']!='BASE_REELS' or any(type(s[k]) is not int or s[k]!=0 for k in ('portalSpinsAwarded','portalSpinsLeft','lastChangeOfWinWays')) or s['pickAndClickResult'] is not None:return False
 if s['portalReels']!=[False]*width or not all(type(v) is bool for v in s['portalReels']):return False
 if s['stateChanges']!=[{'type':'NO_CHANGE','portalState':[],'affectedReels':[]}]:return False
 if s['numberOfLines']!=definition['NonPortalReelHeight']**width or type(s['numberOfLines']) is not int or number(s['betAmount'])!=stake or number(s['coinsPerBet'])!=definition['CoinsPerBetNormal']:return False
 for key in ('reelsPositions','previousReelsPositions'):
  if not isinstance(s[key],list) or len(s[key])!=width or not all(type(v) is int and v>=0 for v in s[key]):return False
 for key in ('reels','previousReels'):
  if not isinstance(s[key],list) or len(s[key])!=width or not all(isinstance(v,str) and 1<=len(v)<=128 and v.startswith('Base') for v in s[key]):return False
 return True

def ordinary(b,constraints):
 try:
  definition=declaration((constraints or {}).get('portal_definition'))
  if definition is None or b['step']!=1 or b['status']!='RESULTED':return False
  bd=b['betdata'];ed=b['eventdata'];rsp=ed['response'];cd=rsp['clientData'];stake=number(bd['cashBet']);coin=number(bd['coin'])
  if set(bd)-{'initialBalance','cmds'}!={'coin','cashBet','cmd','accWa','accC'} or set(ed)-{'boostData','nextCmds'}!={'accC','accWa','initialPlayerState','playerState','response'} or set(rsp)!={'coinWin','cashWin','clientData'}:return False
  if bd['cmd']!='BASE_SPIN' or stake!=number(constraints['basic_amount']) or coin!=number(constraints['basic_coin']) or coin<=0 or stake!=coin*definition['CoinsPerBetNormal'] or number(b['betamount'])!=stake:return False
  if 'initialBalance' in bd:number(bd['initialBalance'])
  if any(command_values(obj.get(key)) not in ([],['C']) for obj,key in ((bd,'cmds'),(ed,'nextCmds'))):return False
  if 'boostData' in ed and ed['boostData']!={'vortexCreated':False}:return False
  keys={'accC','accWa','extraFreeSpins','extraWilds','gameStateAtSpinEnd','gameStateAtSpinStart','numberOfLinesAtSpinEnd','numberOfLinesAtSpinStart','reelSet','reels','rpos','waysOfWinning','waysOfWinningMultipliers','wonCoins','wts','wtw'}
  if not isinstance(cd,dict) or set(cd)!=keys or cd['reelSet']!='BASE_REELS' or type(cd['extraFreeSpins']) is not int or type(cd['extraWilds']) is not int or cd['extraFreeSpins']!=definition['FreeSpinsBase'] or cd['extraWilds']!=definition['ExtraWilds']:return False
  board=cd['reels']
  if not isinstance(board,list) or not 1<=len(board)<=20 or not all(isinstance(col,list) and len(col)==definition['WindowHeight'] and 1<=len(col)<=64 and all(isinstance(v,str) and 1<=len(v)<=128 for v in col) for col in board):return False
  width=len(board);cells=sum(map(len,board));before=cd['gameStateAtSpinStart'];after=cd['gameStateAtSpinEnd']
  if not all(neutral(s,width,definition,stake) for s in (before,after,ed['initialPlayerState'],ed['playerState'])) or before!=after or after!=ed['playerState']:return False
  if cd['rpos']!=after['reelsPositions'] or any(type(cd[k]) is not int or cd[k]!=after['numberOfLines'] for k in ('numberOfLinesAtSpinStart','numberOfLinesAtSpinEnd')):return False
  ways=cd['waysOfWinning'];mult=cd['waysOfWinningMultipliers']
  if not isinstance(ways,list) or not 1<=len(ways)<=4096 or not isinstance(mult,list) or len(mult)!=len(ways) or not all(type(v) is int and v>=0 for v in ways) or not all(isinstance(v,list) and len(v)<=256 and all(type(x) is int and x>=0 for x in v) for v in mult):return False
  wins=cd['wtw']
  if not isinstance(wins,list) or len(wins)>4096 or not all(classic_win(v,cells) for v in wins):return False
  won=number(cd['wonCoins']);cash=won*coin
  if sum(number(v[1]) for v in wins)!=won:return False
  if not isinstance(cd['wts'],list) or len(cd['wts'])>256 or not all(isinstance(v,str) and 1<=len(v)<=4096 and set(v)<={'0','1'} for v in cd['wts']):return False
  if any(number(v)!=won for v in (cd['accC'],bd['accC'],ed['accC'],rsp['coinWin'])) or any(number(v)!=cash for v in (cd['accWa'],bd['accWa'],ed['accWa'],rsp['cashWin'])):return False
  return number(b['wonamount']) in (number(0),cash)
 except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError):return False
