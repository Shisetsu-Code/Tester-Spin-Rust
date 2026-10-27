"""Cash-normalized ActionGame DTOs, bound to the current paid BASE_SPIN.

No unknown action, counter, source or game mode is treated as presentation.
Only one complete base evaluation with checked current cash totals is ordinary.
"""
from decimal import Decimal
import re
from .named_actions import _number
from .protocol import command_values

COMMON={'$type','animationIdentifier','actionSource'}
PREFIX='ActionGame_'

def _action(action,kind,fields):
    return (isinstance(action,dict) and set(action)==COMMON|set(fields)
        and action['$type']==PREFIX+kind and action['animationIdentifier']=='Default'
        and action['actionSource']=={'$type':'ActionSource_Empty'})

def _money(value,stake,currency):
    if not isinstance(value,dict) or set(value)!={'currency','amount','amountNormalizedToBet'} or value['currency']!=currency or not all(_number(value[k]) for k in ('amount','amountNormalizedToBet')):return None
    amount=Decimal(str(value['amount']))
    return amount if Decimal(str(value['amountNormalizedToBet']))*stake==amount else None

def _board(value):
    if not isinstance(value,dict) or set(value)!={'cells','counters'} or value['counters']!=[]:return None
    cells=value['cells']
    if not isinstance(cells,list) or not 1<=len(cells)<=1280:return None
    result={}
    for cell in cells:
        if not isinstance(cell,dict) or set(cell)!={'position','counters','symbol'} or cell['counters']!=[]:return None
        pos=cell['position'];symbol=cell['symbol']
        if not isinstance(pos,dict) or set(pos)!={'x','y'} or type(pos['x']) is not int or type(pos['y']) is not int or not 0<=pos['x']<20 or not 0<=pos['y']<64:return None
        if not isinstance(symbol,dict) or set(symbol)!={'symbolCode','counters'} or symbol['counters']!=[] or not isinstance(symbol['symbolCode'],str) or not 1<=len(symbol['symbolCode'])<=128:return None
        key=(pos['x'],pos['y'])
        if key in result:return None
        result[key]=symbol['symbolCode']
    width=max(x for x,y in result)+1;height=max(y for x,y in result)+1
    return result if len(result)==width*height else None

def ordinary_typed_actions(bet):
    if not isinstance(bet,dict) or type(bet.get('step')) is not int or bet['step']!=1 or not _number(bet.get('betamount'),positive=True):return False
    currency=bet.get('betcurrency')
    if not isinstance(currency,str) or not re.fullmatch(r'[A-Z]{3}',currency):return False
    stake=Decimal(str(bet['betamount']));bd=bet.get('betdata');ed=bet.get('eventdata')
    bdkeys={'coin','cashBet','cmd','accWa','accC'}
    if not isinstance(bd,dict) or not bdkeys<=set(bd)<=bdkeys|{'initialBalance','cmds'} or bd['cmd']!='BASE_SPIN':return False
    if 'cmds' in bd and bd['cmds'] not in ([],['C'],'C',''):return False
    if not all(_number(bd[k]) for k in ('coin','cashBet','accWa','accC')) or Decimal(str(bd['cashBet']))!=stake or Decimal(str(bd['coin']))!=stake or Decimal(str(bd['accC']))!=0:return False
    if 'initialBalance' in bd and not _number(bd['initialBalance']):return False
    if not isinstance(ed,dict) or set(ed) not in ({'accC','accWa','response'},{'accC','accWa','response','nextCmds'}) or not all(_number(ed[k]) for k in ('accC','accWa')) or Decimal(str(ed['accC']))!=0:return False
    if 'nextCmds' in ed and ed['nextCmds'] not in ([],['C'],'C',''):return False
    response=ed['response']
    if not isinstance(response,dict) or set(response)!={'coinWin','cashWin','clientData'} or not _number(response['coinWin']) or Decimal(str(response['coinWin']))!=0 or not _number(response['cashWin']):return False
    cd=response['clientData']
    if not isinstance(cd,dict) or set(cd)!={'actions','isFinished'} or cd['isFinished'] is not True:return False
    actions=cd['actions']
    if not isinstance(actions,list) or not 5<=len(actions)<=260:return False
    if not _action(actions[0],'PresentModeStart',{'modeName'}) or actions[0]['modeName']!='base_game':return False
    if not _action(actions[1],'NewSpin',{'board'}):return False
    board=_board(actions[1]['board'])
    if board is None:return False
    if not _action(actions[2],'FeatureHappened',{'featureIdentifier'}) or actions[2]['featureIdentifier']!='win_evaluation_started':return False
    index=3;total=Decimal(0);wins=0
    while index<len(actions) and isinstance(actions[index],dict) and actions[index].get('$type')==PREFIX+'PresentWinCombination':
        action=actions[index]
        if not _action(action,'PresentWinCombination',{'win','winningCells'}):return False
        amount=_money(action['win'],stake,currency);positions=action['winningCells']
        if amount is None or amount<=0 or not isinstance(positions,list) or not 1<=len(positions)<=len(board):return False
        seen=set()
        for pos in positions:
            if not isinstance(pos,dict) or set(pos)!={'x','y'} or any(type(v) is not int for v in pos.values()):return False
            key=(pos['x'],pos['y'])
            if key in seen or key not in board or board[key]=='empty':return False
            seen.add(key)
        total+=amount;wins+=1;index+=1
    if index>=len(actions) or not _action(actions[index],'FeatureHappened',{'featureIdentifier'}) or actions[index]['featureIdentifier']!='win_evaluation_finished':return False
    index+=1
    if wins:
        if index>=len(actions) or not _action(actions[index],'PresentIntermediateWin',{'win','accumulatedRoundWin'}):return False
        if any(_money(actions[index][k],stake,currency)!=total for k in ('win','accumulatedRoundWin')):return False
        index+=1
    if index!=len(actions)-1 or not _action(actions[index],'PresentModeWin',{'modeWin','accumulatedRoundWin'}):return False
    if any(_money(actions[index][k],stake,currency)!=total for k in ('modeWin','accumulatedRoundWin')):return False
    return all(Decimal(str(value))==total for value in (bd['accWa'],ed['accWa'],response['cashWin']))
