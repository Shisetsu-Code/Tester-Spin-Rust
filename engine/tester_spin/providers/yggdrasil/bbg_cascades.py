"""BBG cascades: current server symbol, position and payout declarations.

This checks server-provided awards, including its current paytable; never inferred purchases.
Unknown controls or reward types remain unsupported.
"""
from decimal import Decimal,InvalidOperation
import re

REWARDS={'','DoubleWild','MultiplierIncrease','WildStack','ExtraLife'}
CASCADE={'leftMultiplier','rightMultiplier','wildOffSets','rewardCollected','rewardAwarded','cascadeProgressCount','cascadeGrid','doubleWildOffset','wildStackOffsets','cascadeIndex','offsetsToRemove','currentWinnings','accumulativeWinnings','wins'}
PRIZE={'id','type','method','winnings','payoutFactor','multiplier','wildMultiplier','symbolPos','lineIndex','stake','winSymbols'}

def cash(value):
    if isinstance(value,bool):return None
    try:amount=Decimal(str(value))
    except (InvalidOperation,ValueError):return None
    return amount if amount.is_finite() and amount>=0 else None

def grid_shape(board):
    if not isinstance(board,list) or not 1<=len(board)<=20 or not all(isinstance(col,list) and 1<=len(col)<=64 and all(type(v) is int and 0<=v<=65535 for v in col) for col in board):return None
    return (len(board),len(board[0])) if len({len(col) for col in board})==1 else None

def definition_contract(definition):
    if not isinstance(definition,dict):return None
    view=definition.get('viewDefs');symbols=definition.get('symbolDefs');wins=definition.get('winDefs')
    if not isinstance(view,dict) or set(view)!={'type','view'} or view['type']!='grid' or grid_shape(view['view']) is None:return None
    coordinates={value:(c,r) for c,col in enumerate(view['view']) for r,value in enumerate(col)}
    shape=grid_shape(view['view'])
    if len(coordinates)!=shape[0]*shape[1] or not isinstance(symbols,dict) or not 1<=len(symbols)<=4096 or not isinstance(wins,dict) or not 1<=len(wins)<=65536:return None
    symbol_ids=set();wilds=set()
    for key,entry in symbols.items():
        if not isinstance(key,str) or not re.fullmatch(r'0|[1-9][0-9]{0,4}',key) or int(key)>65535 or not isinstance(entry,dict) or set(entry)!={'isWild','displayName'} or type(entry['isWild']) is not bool or not isinstance(entry['displayName'],str) or not 1<=len(entry['displayName'])<=128:return None
        symbol_ids.add(int(key))
        if entry['isWild']:wilds.add(int(key))
    prices={}
    for key,entry in wins.items():
        if not isinstance(key,str) or len(key)>128 or not re.fullmatch(r'[0-9]+:[1-9][0-9]*',key) or not isinstance(entry,dict) or set(entry)!={'symbol','freq','payoutFactor','type'}:return None
        symbol,count=map(int,key.split(':'))
        if symbol not in symbol_ids or entry['symbol']!=str(symbol) or type(entry['freq']) is not int or entry['freq']!=count or not 1<=count<=shape[0] or cash(entry['payoutFactor']) is None or not isinstance(entry['type'],str) or not 1<=len(entry['type'])<=64:return None
        prices[key]=entry
    return {'coordinates':coordinates,'shape':shape,'symbols':symbol_ids,'wilds':wilds,'prices':prices}

def _indexes(values,positions):
    return isinstance(values,list) and len(values)<=len(positions) and all(type(p) is int and p in positions for p in values) and len(set(values))==len(values)

def _prize(prize,board,stake,contract,row):
    if not isinstance(prize,dict) or set(prize)!=PRIZE or prize['type']!='ways' or prize['method'] not in ('LtoR','RtoL') or type(prize['lineIndex']) is not int or prize['lineIndex']!=-1:return None
    identifier=prize['id']
    if not isinstance(identifier,str) or len(identifier)>128 or not re.fullmatch(r'[0-9]+:[1-9][0-9]*',identifier):return None
    symbol,count=map(int,identifier.split(':'));width,height=grid_shape(board)
    price=contract['prices'].get(identifier)
    if price is None or price['type']!=prize['type'] or cash(price['payoutFactor'])!=cash(prize['payoutFactor']):return None
    coordinates=contract['coordinates']
    positions=prize['symbolPos'];symbols=prize['winSymbols']
    if not _indexes(positions,coordinates) or len(positions)!=count or not 1<=count<=width or not isinstance(symbols,list) or len(symbols)!=count or any(type(v) is not int for v in symbols):return None
    if symbols!=[board[coordinates[p][0]][coordinates[p][1]] for p in positions] or any(value!=symbol and value not in contract['wilds'] for value in symbols):return None
    columns={coordinates[p][0] for p in positions}
    if columns!=set(range(count) if prize['method']=='LtoR' else range(width-count,width)):return None
    if any(type(prize[k]) is not int or not 1<=prize[k]<=1000000 for k in ('multiplier','wildMultiplier')):return None
    expected=row['leftMultiplier']+row['rightMultiplier'] if count==width else row['leftMultiplier'] if prize['method']=='LtoR' else row['rightMultiplier']
    if prize['multiplier']!=expected or prize['wildMultiplier']!=1:return None
    amount=cash(prize['winnings']);factor=cash(prize['payoutFactor'])
    if amount is None or factor is None or amount<=0 or factor<=0 or cash(prize['stake'])!=stake or amount!=stake*factor*prize['multiplier']*prize['wildMultiplier']:return None
    return amount

def cascade_cash(cd,definition=None):
    contract=definition_contract(definition)
    if contract is None or not isinstance(cd,dict):return None
    shape=grid_shape(cd.get('initialGrid'))
    if shape!=contract['shape'] or grid_shape(cd.get('finalGrid'))!=shape or cd.get('wins')!=[]:return None
    coordinates=contract['coordinates']
    if any(v not in contract['symbols'] for board in (cd['initialGrid'],cd['finalGrid']) for col in board for v in col):return None
    stake=cash(cd.get('stake'));current=cash(cd.get('currentWinnings'))
    if stake is None or stake<=0 or current is None:return None
    cascades=cd.get('cascadeDetails',[])
    if not isinstance(cascades,list) or len(cascades)>256:return None
    if not cascades:return Decimal(0) if current==0 and cd['initialGrid']==cd['finalGrid'] else None
    running=Decimal(0);width,height=shape;cells=coordinates;extra_lives=0
    for index,row in enumerate(cascades):
        if not isinstance(row,dict) or set(row) not in (CASCADE,CASCADE|{'extraLifeRemoveOffset'}) or type(row['cascadeIndex']) is not int or row['cascadeIndex']!=index or grid_shape(row['cascadeGrid'])!=shape:return None
        if any(v not in contract['symbols'] for col in row['cascadeGrid'] for v in col):return None
        if index==0 and row['cascadeGrid']!=cd['initialGrid']:return None
        if any(type(row[k]) is not int or not 1<=row[k]<=1000000 for k in ('leftMultiplier','rightMultiplier')):return None
        progress=row['cascadeProgressCount']
        if type(progress) is not int or not 0<=progress<=1000000:return None
        if progress==0:
            if row['wins']!=[] or row['offsetsToRemove']!=[]:return None
            if index==len(cascades)-1:
                if row['cascadeGrid']!=cd['finalGrid']:return None
            elif not isinstance(cascades[index+1],dict) or cascades[index+1].get('rewardAwarded')!='ExtraLife' or 'extraLifeRemoveOffset' not in cascades[index+1]:return None
        if any(not isinstance(row[k],str) or row[k] not in REWARDS for k in ('rewardCollected','rewardAwarded')):return None
        if row['rewardCollected']=='ExtraLife':extra_lives+=1
        if row['rewardAwarded']=='ExtraLife':
            if extra_lives<1 or index==0 or 'extraLifeRemoveOffset' not in row:return None
            previous=cascades[index-1]
            if previous['wins']!=[] or previous['offsetsToRemove']!=[] or cash(previous['currentWinnings'])!=0:return None
            replacements=row['extraLifeRemoveOffset']
            if not _indexes(replacements,cells) or set(replacements)!={p for p,(c,r) in coordinates.items() if previous['cascadeGrid'][c][r] not in contract['wilds']}:return None
            for p in coordinates:
                if p in replacements:continue
                column,old_row=coordinates[p]
                drop=sum(coordinates[q][0]==column and coordinates[q][1]>old_row for q in replacements)
                if old_row+drop>=height or row['cascadeGrid'][column][old_row+drop] not in contract['wilds']:return None
            extra_lives-=1
        elif 'extraLifeRemoveOffset'in row:return None
        if any(not _indexes(row[k],cells) for k in ('wildOffSets','wildStackOffsets','offsetsToRemove')) or type(row['doubleWildOffset']) is not int or row['doubleWildOffset']!=-1 and row['doubleWildOffset'] not in cells:return None
        wins=row['wins']
        if not isinstance(wins,list) or len(wins)>65536:return None
        amounts=[_prize(win,row['cascadeGrid'],stake,contract,row) for win in wins]
        if any(amount is None for amount in amounts):return None
        subtotal=sum(amounts,Decimal(0))
        if cash(row['currentWinnings'])!=subtotal:return None
        if wins and set(row['offsetsToRemove'])!={p for win in wins for p in win['symbolPos']}:return None
        running+=subtotal
        if cash(row['accumulativeWinnings'])!=running:return None
    return running if running==current else None


def ordinary_dto(cd):
    from .parameter_choices import BBG_ROOT
    return isinstance(cd,dict) and BBG_ROOT<=set(cd)<=BBG_ROOT|{'cascadeDetails'}

def _settled_player_state(state,constraints=None):
    from .parameter_choices import BBG_ROOT
    seed={'stake','totalStake','currentWinnings','totalWinnings','baseGameWinnings','finished'}
    if not isinstance(state,dict):return False
    if set(state)==seed:return state['finished'] is False and all(cash(state[k])==0 for k in seed-{'finished'})
    fields=BBG_ROOT-{'wins'}
    if not fields<=set(state)<=fields|{'freeSpinState'} or state['finished'] is not True or state['nextActions']!=['Spin'] or state['currentAction'] not in ('Spin','FreeSpin'):return False
    if state['gambleAwarded'] is not False or state['isWinCapped'] is not False or type(state['freeSpinsAwarded']) is not int or state['freeSpinsAwarded']!=0:return False
    flags=('isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive')
    if any(type(state[k]) is not bool for k in flags) or sum(state[k] for k in flags)>1:return False
    if state['reelId'] not in ('BaseGame','GoldenBetGame','FreeGame'):return False
    if any(type(state[k]) is not int or not 1<=state[k]<=1000000 for k in ('leftMultiplier','rightMultiplier','nextLeftIncrement','nextRightIncrement')):return False
    if any(not isinstance(state[k],str) or not 1<=len(state[k])<=128 for k in ('version','name')):return False
    if grid_shape(state['initialGrid']) is None or grid_shape(state['initialGrid'])!=grid_shape(state['finalGrid']):return False
    if any(cash(state[k]) is None for k in ('stake','totalStake','currentWinnings','totalWinnings','baseGameWinnings')) or cash(state['stake'])<=0 or cash(state['totalStake'])<=0:return False
    if cash(state['totalWinnings'])<max(cash(state['currentWinnings']),cash(state['baseGameWinnings'])):return False
    if 'freeSpinState'in state:
        fs=state['freeSpinState']
        if state['currentAction']!='FreeSpin' or not isinstance(fs,dict) or set(fs)!={'id','spinsRemaining','currentPlay','spinsAwarded','accumulatedWinnings','triggeringDetails'}:return False
        if fs['id']!='FreeSpin' or type(fs['spinsRemaining']) is not int or fs['spinsRemaining']!=0 or type(fs['currentPlay']) is not int or type(fs['spinsAwarded']) is not int or not 1<=fs['currentPlay']==fs['spinsAwarded']<=1000 or cash(fs['accumulatedWinnings']) is None:return False
        tr=fs['triggeringDetails']
        if not isinstance(tr,dict) or set(tr) not in ({'view','symbol'},{'view','symbol','offsets'}) or type(tr['symbol']) is not int or not 0<=tr['symbol']<=65535 or grid_shape(tr['view']) is None:return False
        if 'offsets'in tr:
            contract=definition_contract((constraints or {}).get('bbg_definition'))
            if contract is None or grid_shape(tr['view'])!=contract['shape'] or not _indexes(tr['offsets'],contract['coordinates']):return False
            if set(tr['offsets'])!={p for p,(c,r) in contract['coordinates'].items() if tr['view'][c][r]==tr['symbol']}:return False
    elif state['currentAction']!='Spin':return False
    return True

def _ordinary_envelope(bd,ed,cd,constraints=None):
    from .protocol import command_values
    core={'coin','cashBet','cmd','accWa','accC'}
    known={'accC','accWa','initialPlayerState','playerState','response'}
    if not core<=set(bd)<=core|{'initialBalance','cmds'} or not known<=set(ed)<=known|{'boostData','nextCmds'} or set(ed['response'])!={'coinWin','cashWin','clientData'}:return False
    commands=command_values(ed.get('nextCmds'))
    if commands not in ([],['C']) or not _settled_player_state(ed['initialPlayerState'],constraints):return False
    if commands==['C']:
        if ed.get('nextCmds') not in ('C',['C']) or bd.get('cmds')!=['C']:return False
    elif cash(cd.get('currentWinnings'))!=0 or 'nextCmds'in ed and ed['nextCmds'] not in ('',[]) or 'cmds'in bd and bd['cmds']!=[]:return False
    if ed['playerState']!={k:v for k,v in cd.items() if k not in {'wins','cascadeDetails'}}:return False
    if 'initialBalance'in bd and cash(bd['initialBalance']) is None:return False
    if not all(cash(value) is not None for value in (bd['accWa'],bd['accC'],ed['accC'],ed['response']['coinWin'])) or cash(bd['accC'])!=cash(ed['accC']) or cash(ed['accC'])!=cash(ed['response']['coinWin']):return False
    return boost_data_valid(ed.get('boostData'))

def boost_data_valid(boost):
    if boost is not None:
        if not isinstance(boost,dict) or set(boost)!={'data'} or not isinstance(boost['data'],list) or len(boost['data'])>256:return False
        for mission in boost['data']:
            if not isinstance(mission,dict) or set(mission)!={'mission','goal','progress','states'} or not isinstance(mission['mission'],str) or not 1<=len(mission['mission'])<=128 or type(mission['goal']) is not int or type(mission['progress']) is not int or not 0<=mission['progress']<=1000000 or not 0<mission['goal']<=1000000 or mission['goal']==0 or mission['states']!=[]:return False
    return True

def ordinary_cascade(bet,constraints=None):
    if not isinstance(bet,dict) or type(bet.get('step')) is not int or bet.get('step')!=1 or bet.get('status')!='RESULTED':return False
    bd=bet.get('betdata');ed=bet.get('eventdata')
    if not isinstance(bd,dict) or not isinstance(ed,dict) or not isinstance(ed.get('response'),dict):return False
    cd=ed['response'].get('clientData')
    if not ordinary_dto(cd) or cd['finished'] is not True or cd['currentAction']!='Spin' or cd['nextActions']!=['Spin'] or cd['reelId']!='BaseGame':return False
    if not _ordinary_envelope(bd,ed,cd,constraints):return False
    if any(cd[k] is not False for k in ('isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive','gambleAwarded','isWinCapped')) or type(cd['freeSpinsAwarded']) is not int or cd['freeSpinsAwarded']!=0:return False
    if any(type(cd[k]) is not int or not 1<=cd[k]<=1000000 for k in ('leftMultiplier','rightMultiplier','nextLeftIncrement','nextRightIncrement')):return False
    if any(not isinstance(cd[k],str) or not 1<=len(cd[k])<=128 for k in ('version','name')):return False
    paid=cash(bet.get('betamount'))
    if paid is None or paid<=0 or bd.get('cmd')!='BASE_SPIN' or any(cash(value)!=paid for value in (bd.get('coin'),bd.get('cashBet'),cd['stake'],cd['totalStake'])):return False
    won=cascade_cash(cd,(constraints or {}).get('bbg_definition'))
    return won is not None and all(cash(value)==won for value in (cd['totalWinnings'],cd['baseGameWinnings'],bd.get('accWa'),ed.get('accWa'),ed['response'].get('cashWin')))


def acknowledged_envelope(bet,commands,previous_state=None):
    from .protocol import command_values
    if bet.get('status')!='RESULTED' or not isinstance(bet.get('betdata'),dict) or not isinstance(bet.get('eventdata'),dict):return False
    bd=bet['betdata'];ed=bet['eventdata'];required={'coin','cashBet','cmd','accWa','accC','cmds'}
    known={'accC','accWa','initialPlayerState','nextCmds','playerState','response'}
    if not required<=set(bd)<=required|{'initialBalance','clientParams'} or not known<=set(ed)<=known|{'boostData'} or not isinstance(ed['response'],dict) or set(ed['response'])!={'coinWin','cashWin','clientData'}:return False
    cd=ed['response']['clientData']
    if not isinstance(cd,dict) or ed['playerState']!={k:v for k,v in cd.items() if k not in {'wins','cascadeDetails'}} or command_values(ed['nextCmds'])!=commands or command_values(bd['cmds'])!=commands:return False
    if previous_state is not None and ed['initialPlayerState']!=previous_state:return False
    return boost_data_valid(ed.get('boostData'))
