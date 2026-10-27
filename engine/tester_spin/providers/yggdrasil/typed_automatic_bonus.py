"""Recognize a fully presented cash-normalized hold-and-fill bonus.

This is a known FEATURE outcome, never a base outcome. The runtime must still
collect the same wager and then prove two separate ordinary BASIC rounds.
"""
from decimal import InvalidOperation
import re
from .supermeter import num
from .typed_actions import _action, _money
from .protocol import command_values


def _position(value):
    if not isinstance(value,dict) or set(value)!={'x','y'} or any(type(v) is not int for v in value.values()):return None
    x,y=value['x'],value['y']
    return (x,y) if 0<=x<20 and 0<=y<64 else None


def _cell(value):
    if not isinstance(value,dict) or set(value)!={'position','counters','symbol'}:return None
    position=_position(value['position']);symbol=value['symbol']
    if position is None or not isinstance(symbol,dict) or set(symbol)!={'symbolCode','counters'}:return None
    code=symbol['symbolCode']
    if not isinstance(code,str) or not 1<=len(code)<=128:return None
    for counters,allowed in ((value['counters'],{'bonusAwarded'}),(symbol['counters'],{'timesBetWin'})):
        if not isinstance(counters,list) or len(counters)>1:return None
        for counter in counters:
            if not isinstance(counter,dict) or set(counter)!={'name','value'} or counter['name'] not in allowed or type(counter['value']) is not int:return None
            if counter['name']=='bonusAwarded' and counter['value'] not in (0,1):return None
            if counter['name']=='timesBetWin' and (code!='Coin' or not 1<=counter['value']<=1000000):return None
    amount=symbol['counters'][0]['value'] if symbol['counters'] else 0
    return position,(code,amount)


def recognized(bet,constraints):
    try:
        if not isinstance(constraints,dict) or bet['step']!=1 or bet['status']!='RESULTED':return False
        stake=num(constraints['basic_amount']);currency=constraints['currency']
        if stake<=0 or bet['betcurrency']!=currency or num(bet['betamount'])!=stake or num(bet['wonamount'])!=0:return False
        bd=bet['betdata'];ed=bet['eventdata']
        if bd['cmd']!='BASE_SPIN' or num(bd['cashBet'])!=stake or num(bd['coin'])!=stake:return False
        if set(ed)!={'accC','accWa','nextCmds','response'} or command_values(ed['nextCmds'])!=['C']:return False
        response=ed['response'];cd=response['clientData']
        if set(response)!={'coinWin','cashWin','clientData'} or set(cd)!={'actions','isFinished'} or cd['isFinished'] is not True:return False
        if any(num(v)!=0 for v in (bd['accC'],ed['accC'],response['coinWin'])):return False
        total=num(response['cashWin'])
        if total<=0 or any(num(v)!=total for v in (bd['accWa'],ed['accWa'])):return False
        actions=cd['actions']
        if not isinstance(actions,list) or not 12<=len(actions)<=1024:return False
        board={};suffix=None;phase='base';entered=False;intro=False;exited=False;base_win=False;final_win=False
        spins=None;reset=None;filled=False;combination=False;intermediate=False
        for index,action in enumerate(actions):
            kind=action.get('$type','').removeprefix('ActionGame_') if isinstance(action,dict) else ''
            if exited and kind!='PresentModeWin':return False
            if kind=='PresentModeStart':
                if not _action(action,kind,{'modeName'}):return False
                if index==0:
                    if action['modeName']!='BaseGame':return False
                else:
                    if phase!='base' or not entered or not base_win or suffix is None or action['modeName']!='Bonus'+suffix:return False
                    phase='bonus'
            elif kind=='NewSpin':
                if not _action(action,kind,{'board'}):return False
                value=action['board']
                if not isinstance(value,dict) or set(value)!={'cells','counters'} or value['counters']!=[] or not isinstance(value['cells'],list) or not 1<=len(value['cells'])<=1280:return False
                current={}
                for value in value['cells']:
                    cell=_cell(value)
                    if cell is None or cell[0] in current:return False
                    current[cell[0]]=cell[1]
                width=max(x for x,y in current)+1;height=max(y for x,y in current)+1
                if len(current)!=width*height:return False
                board=current
            elif kind=='SpecialSymbolTrigger':
                if phase!='base' or not _action(action,kind,{'positions'}) or not isinstance(action['positions'],list) or not action['positions']:return False
                positions=[_position(v) for v in action['positions']]
                if len(set(positions))!=len(positions) or any(p is None or p not in board for p in positions):return False
            elif kind=='FillEmptyCells':
                if phase!='bonus' or not _action(action,kind,{'cells'}) or not isinstance(action['cells'],list) or not action['cells']:return False
                changed=set()
                for value in action['cells']:
                    cell=_cell(value)
                    if cell is None or cell[0] in changed or cell[0] not in board or board[cell[0]][0] not in ('Empty','None') or cell[1][0]!='Coin' or cell[1][1]<=0:return False
                    changed.add(cell[0]);board[cell[0]]=cell[1]
                filled=True
            elif kind=='SetCounterSymbol':
                if phase!='bonus' or not _action(action,kind,{'position','name','value'}) or action['name']!='timesBetWin' or type(action['value']) is not int:return False
                position=_position(action['position'])
                if position not in board or board[position]!=('Coin',action['value']) or action['value']<=0:return False
            elif kind=='SetCounterBoard':
                if not _action(action,kind,{'name','value'}) or type(action['value']) is not int or not 0<=action['value']<=1280:return False
                if phase=='base' and action['name']=='server_enterBonus':
                    if entered or suffix is None or action['value']<=0:return False
                    entered=True
                elif phase=='bonus' and action['name']=='spinsLeft':
                    value=action['value']
                    if spins is None:
                        if value<=0:return False
                        reset=value
                    elif value!=spins-1 and not (filled and value==reset):return False
                    spins=value;filled=False
                else:return False
            elif kind=='FeatureHappened':
                if not _action(action,kind,{'featureIdentifier'}):return False
                feature=action['featureIdentifier']
                if feature=='spin':
                    if not board:return False
                elif phase=='base' and isinstance(feature,str) and re.fullmatch(r'[A-Za-z]{1,32}BonusAwarded',feature):
                    if suffix is not None:return False
                    suffix=feature.removesuffix('BonusAwarded')
                    if 'BB_'+suffix.upper() not in constraints.get('collection_modes',[]):return False
                elif phase=='bonus' and feature=='bonus'+suffix:pass
                elif phase=='bonus' and feature=='bonusGameIntro':
                    if intro:return False
                    intro=True
                elif phase=='bonus' and feature=='exitBonusGame':
                    if not intro or spins!=0 or not combination or not intermediate:return False
                    exited=True
                else:return False
            elif kind=='PresentWinCombination':
                if action.get('animationIdentifier')!='coinWin':return False
                shape={**action,'animationIdentifier':'Default'}
                if phase!='bonus' or spins!=0 or combination or not _action(shape,kind,{'win','winningCells'}) or action['winningCells']!=[] or _money(action['win'],stake,currency)!=total:return False
                if sum(amount for code,amount in board.values())*stake!=total:return False
                combination=True
            elif kind=='PresentIntermediateWin':
                if not combination or intermediate or not _action(action,kind,{'win','accumulatedRoundWin'}) or any(_money(action[k],stake,currency)!=total for k in ('win','accumulatedRoundWin')):return False
                intermediate=True
            elif kind=='PresentModeWin':
                if not _action(action,kind,{'modeWin','accumulatedRoundWin'}):return False
                expected=0 if phase=='base' else total
                if any(_money(action[k],stake,currency)!=expected for k in ('modeWin','accumulatedRoundWin')):return False
                if phase=='base':
                    if not entered or base_win:return False
                    base_win=True
                elif not exited or index!=len(actions)-1:return False
                else:final_win=True
            else:return False
        return entered and intro and exited and base_win and final_win
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError):return False
