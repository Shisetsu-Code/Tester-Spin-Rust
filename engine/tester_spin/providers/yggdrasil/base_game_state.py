"""Explicit base-game outcome schema; unknown controls are never ignored."""
from decimal import Decimal
from .named_actions import _board,_number

def ordinary_base_game(cd):
    expected={'win','reels','finalBoard','boardHeight','gameMode','reSpinAwarded','bonusGameSpinAwarded','excessiveScattersWinInCoins'}
    if set(cd)!=expected or cd['gameMode']!='BASE_GAME' or cd['reSpinAwarded'] is not False or cd['bonusGameSpinAwarded'] is not False:return False
    board=cd['finalBoard'];height=cd['boardHeight']
    if type(height) is not int or not 1<=height<=64 or not _board(board) or any(len(col)!=height for col in board):return False
    if not _number(cd['excessiveScattersWinInCoins']):return False
    reels=cd['reels']
    if not isinstance(reels,dict) or set(reels)!={'reelSetName','reelStopPositions'} or not isinstance(reels['reelSetName'],str) or not reels['reelSetName']:return False
    stops=reels['reelStopPositions']
    if not isinstance(stops,list) or len(stops)!=len(board) or not all(type(v) is int and v>=0 for v in stops):return False
    win=cd['win'];money={'wonCoins','wonCash','accumulatedWonCoins','accumulatedWonCash','accumulatedRoundWonCoins','accumulatedRoundWonCash'}
    if not isinstance(win,dict) or set(win)!=money|{'prizes'} or not all(_number(win[k]) for k in money):return False
    prizes=win['prizes']
    if not isinstance(prizes,list) or len(prizes)>256:return False
    for prize in prizes:
        common={'symbol','oak','positions','coins','cash'}
        shapes=[common,common|{'ways'},common|{'payline'},common|{'payline','multiplier','coinsBeforeMultiplier','cashBeforeMultiplier'}]
        if not isinstance(prize,dict) or set(prize) not in shapes:return False
        if 'ways' in prize and (type(prize['ways']) is not int or prize['ways']<=0):return False
        if 'payline' in prize and (type(prize['payline']) is not int or prize['payline']<0):return False
        if 'multiplier' in prize and (not _number(prize['multiplier'],positive=True) or not all(_number(prize[k]) for k in ('coinsBeforeMultiplier','cashBeforeMultiplier'))):return False
        if not isinstance(prize['symbol'],str) or not prize['symbol'] or not all(_number(prize[k]) for k in ('coins','cash')):return False
        if not all(type(prize[k]) is int and prize[k]>0 for k in ('oak',)):return False
        positions=prize['positions']
        if not isinstance(positions,list) or not 1<=len(positions)<=1280:return False
        for pos in positions:
            if not isinstance(pos,dict) or set(pos)!={'x','y'} or type(pos['x']) is not int or type(pos['y']) is not int or not 0<=pos['x']<len(board) or not 0<=pos['y']<height:return False
    return True


def ordinary_no_award(cd):
    if not isinstance(cd,dict) or set(cd)!={'win','reels','initialBoard','finalBoard','freeSpinsAwarded'} or type(cd['freeSpinsAwarded']) is not int or cd['freeSpinsAwarded']!=0:return False
    board=cd['finalBoard']
    if not _board(board) or not _board(cd['initialBoard']) or [len(x) for x in board]!=[len(x) for x in cd['initialBoard']]:return False
    return ordinary_base_game({'win':cd['win'],'reels':cd['reels'],'finalBoard':board,'boardHeight':len(board[0]),'gameMode':'BASE_GAME','reSpinAwarded':False,'bonusGameSpinAwarded':False,'excessiveScattersWinInCoins':0})


def ordinary_numeric_grid(cd):
    import re
    keys={'stake','totalStake','finished','currentAction','nextActions','finalGrid','gigaReelConfig','gigaOffsets','gameModeSet','wins','totalWinnings','baseGameWinnings','currentWinnings'}
    if not isinstance(cd,dict) or set(cd)!=keys or cd['finished'] is not True or cd['currentAction']!='Spin' or cd['nextActions']!=['Spin'] or not isinstance(cd['gameModeSet'],str) or not re.fullmatch(r'BaseGame[0-9]+',cd['gameModeSet']):return False
    if not all(_number(cd[k]) for k in ('stake','totalStake','totalWinnings','baseGameWinnings','currentWinnings')) or cd['stake']!=cd['totalStake']:return False
    grid=cd['finalGrid']
    if not isinstance(grid,list) or not 1<=len(grid)<=20 or not all(isinstance(col,list) and 1<=len(col)<=64 and all(type(x) is int and 0<=x<=4096 for x in col) for col in grid):return False
    if len({len(x) for x in grid})!=1 or type(cd['gigaReelConfig']) is not int or cd['gigaReelConfig']<0:return False
    offsets=cd['gigaOffsets']
    if not isinstance(offsets,list) or len(offsets)>20 or not all(type(x) is int and -64<=x<=64 for x in offsets):return False
    # Positive wins use a separate unlearned schema; never discard them.
    return cd['wins']==[] and all(Decimal(str(cd[k]))==0 for k in ('totalWinnings','baseGameWinnings','currentWinnings'))


def ordinary_board_win(cd):
    core={'win','initialBoard','finalBoard'}
    variants=[core,core|{'reels'},core|{'gigabloxData'},core|{'gigabloxData','rowsNumber','goldenBet','multiplier'},core|{'gigabloxData','reels','totalWin','coinWin','capLimitReached'}]
    if not isinstance(cd,dict) or set(cd) not in variants:return False
    board=cd['finalBoard'];initial=cd['initialBoard']
    if not _board(board) or not _board(initial) or [len(x) for x in board]!=[len(x) for x in initial] or len({len(x) for x in board})!=1:return False
    height=len(board[0]);width=len(board)
    if 'goldenBet' in cd and (cd['goldenBet'] is not False or not _number(cd['multiplier'],positive=True) or type(cd['rowsNumber']) is not int or not 1<=cd['rowsNumber']<=height):return False
    if 'capLimitReached' in cd and (cd['capLimitReached'] is not False or not all(_number(cd[k]) for k in ('totalWin','coinWin'))):return False
    if 'gigabloxData' in cd:
        blocks=cd['gigabloxData']
        if not isinstance(blocks,list) or len(blocks)>20:return False
        for block in blocks:
            if not isinstance(block,dict) or set(block)!={'columns','details','blockStartRowIndex'}:return False
            cols=block['columns'];start=block['blockStartRowIndex'];detail=block['details']
            if not isinstance(cols,list) or not cols or not all(type(x) is int and 0<=x<width for x in cols) or len(set(cols))!=len(cols) or type(start) is not int or not -height<=start<height or not isinstance(detail,dict):return False
            if set(detail)=={'columnIcons'}:
                if not isinstance(detail['columnIcons'],list) or len(detail['columnIcons'])!=height or not all(isinstance(x,str) and x for x in detail['columnIcons']):return False
            elif set(detail)=={'blocks'}:
                items=detail['blocks']
                if not isinstance(items,list) or len(items)>128:return False
                for item in items:
                    if not isinstance(item,dict) or set(item)!={'position','icon','size'} or not isinstance(item['icon'],str) or not item['icon'] or type(item['size']) is not int or not 1<=item['size']<=min(width,height):return False
                    pos=item['position']
                    if not isinstance(pos,dict) or set(pos)!={'x','y'} or type(pos['x']) is not int or type(pos['y']) is not int or pos['x'] not in cols or not -height<=pos['y']<height:return False
            else:return False
    # Reuse the prize/board shape validator. These derived fields validate geometry,
    # not wire evidence of game mode; the runtime separately validates the BASIC wager.
    reels=cd.get('reels',{'reelSetName':'derived-geometry','reelStopPositions':[0]*width})
    return ordinary_base_game({'win':cd['win'],'reels':reels,'finalBoard':board,'boardHeight':height,'gameMode':'BASE_GAME','reSpinAwarded':False,'bonusGameSpinAwarded':False,'excessiveScattersWinInCoins':0})


def ordinary_multiplier_base(cd):
    keys={'win','reels','initialBoard','finalBoard','gameMode','finalMultipliers','accumulatedAvalancheSessionWonCoins','accumulatedAvalancheSessionWonCash','freeSpinsLeft','totalWin','coinWinAdjustedToMaxWinCap','capLimitReached','respin','lastRespin'}
    if not isinstance(cd,dict) or set(cd)!=keys or cd['gameMode']!='BASE_GAME' or type(cd['freeSpinsLeft']) is not int or cd['freeSpinsLeft']!=0 or cd['respin'] is not False or cd['lastRespin'] is not True or cd['capLimitReached'] is not False:return False
    multipliers=cd['finalMultipliers']
    if not isinstance(multipliers,list) or not _board(cd['finalBoard']) or len(multipliers)!=len(cd['finalBoard']) or not all(_number(v,positive=True) for v in multipliers):return False
    if not all(_number(cd[k]) for k in ('accumulatedAvalancheSessionWonCoins','accumulatedAvalancheSessionWonCash','totalWin','coinWinAdjustedToMaxWinCap')):return False
    return ordinary_no_award({k:cd[k] for k in ('win','reels','initialBoard','finalBoard')}|{'freeSpinsAwarded':0})


def ordinary_numeric_bonus_flags(cd):
    keys={'screen','winningRows','cashPrizes','modifiersData','bonusData','wagerId'}
    if not isinstance(cd,dict) or set(cd)!=keys or cd['winningRows']!=[] or not isinstance(cd['wagerId'],str) or not 1<=len(cd['wagerId'])<=512:return False
    grid=cd['screen']
    if not isinstance(grid,list) or not 1<=len(grid)<=20 or not all(isinstance(col,list) and 1<=len(col)<=64 and all(type(x) is int and 0<=x<=4096 for x in col) for col in grid):return False
    bonus=cd['bonusData'];mod=cd['modifiersData']
    if not isinstance(bonus,dict) or set(bonus)!={'bonusTriggered','freespinsAwarded'} or bonus['bonusTriggered'] is not False or type(bonus['freespinsAwarded']) is not int or bonus['freespinsAwarded']!=0:return False
    if not isinstance(mod,dict) or set(mod)!={'currentMultipliers','activeMultiplier','collectFish','collectedCashPrize'} or mod['collectFish'] is not False or not _number(mod['collectedCashPrize']) or Decimal(str(mod['collectedCashPrize']))!=0:return False
    multipliers=mod['currentMultipliers']
    if not isinstance(multipliers,list) or not 1<=len(multipliers)<=256 or not all(_number(x,positive=True) for x in multipliers) or not _number(mod['activeMultiplier'],positive=True) or mod['activeMultiplier'] not in multipliers:return False
    prizes=cd['cashPrizes']
    if not isinstance(prizes,list) or len(prizes)>1280:return False
    for prize in prizes:
        if not isinstance(prize,dict) or set(prize)!={'cashPrize','position'} or not _number(prize['cashPrize']):return False
        pos=prize['position']
        if not isinstance(pos,dict) or set(pos)!={'reel','row'} or type(pos['reel']) is not int or type(pos['row']) is not int or not 0<=pos['reel']<len(grid) or not 0<=pos['row']<len(grid[pos['reel']]):return False
    return True


def ordinary_multiplier_board(cd):
    core={'win','initialBoard','finalBoard','winPositions','multiplier','goldenBet','coinsBeforeMultiplier'}
    if not isinstance(cd,dict) or set(cd) not in (core,core|{'respinAwarded','positionShifts'},core|{'respinAwarded','positionShifts','extraWild'}):return False
    if cd['goldenBet'] is not False or not _number(cd['multiplier'],positive=True) or not _number(cd['coinsBeforeMultiplier']) or 'respinAwarded' in cd and cd['respinAwarded'] is not False:return False
    board=cd['finalBoard']
    if not _board(board):return False
    def position(pos):return isinstance(pos,dict) and set(pos)=={'column','row'} and type(pos['column']) is int and type(pos['row']) is int and 0<=pos['column']<len(board) and 0<=pos['row']<len(board[pos['column']])
    wins=cd['winPositions']
    if not isinstance(wins,list) or len(wins)>1280 or not all(position(p) for p in wins):return False
    shifts=cd.get('positionShifts',[])
    if not isinstance(shifts,list) or len(shifts)>1280 or not all(isinstance(s,dict) and set(s)=={'origin','target'} and all(position(p) for p in s.values()) for s in shifts):return False
    if 'extraWild' in cd and cd['extraWild'] is not None and not position(cd['extraWild']):return False
    return ordinary_board_win({k:cd[k] for k in ('win','initialBoard','finalBoard')})

def ordinary_flat_multiplier(cd):
    core={'accC','accWa','reels','finalBoard','wonCoins','wonMoney','wtw'}
    flags={'isFreeSpinsAwarded','isRespin','isRespinAwarded'}
    multipliers={'initialMultiplier','middleMultiplier','finalMultiplier'}
    simple=core|{'coinsBeforeMultiplier','multiplier'}
    cascade=core|flags|multipliers|{'accumulatedFreeSpinCoins','wildsFromReels'}
    explicit=cascade|{'win','gameMode','isLastRespin','reSpins','freeSpinsAwarded','freeSpins','accumulatedFreeSpinWonAmount','spinPrizeOaks','coinWinAdjustedToMaxWinCap','capLimitReached','gambleProbability'}
    if not isinstance(cd,dict) or set(cd) not in (simple,cascade,explicit):return False
    board=cd['finalBoard']
    if not _board(board) or cd['reels']!=board or cd['wtw']!=[]:return False
    if not all(_number(cd[k]) for k in ('accC','accWa','wonCoins','wonMoney')):return False
    if any(Decimal(str(cd[k]))!=0 for k in ('wonCoins','wonMoney')):return False
    if set(cd)==simple:return _number(cd['coinsBeforeMultiplier']) and Decimal(str(cd['coinsBeforeMultiplier']))==0 and _number(cd['multiplier'],positive=True)
    if any(cd[k] is not False for k in flags) or cd['wildsFromReels']!=[] or not _number(cd['accumulatedFreeSpinCoins']) or Decimal(str(cd['accumulatedFreeSpinCoins']))!=0:return False
    for k in multipliers:
        if not isinstance(cd[k],list) or len(cd[k])!=len(board) or not all(_number(v,positive=True) for v in cd[k]):return False
    if set(cd)==cascade:return True
    if cd['gameMode']!='BASE_GAME' or cd['isLastRespin'] is not True or cd['reSpins'] is not False or cd['capLimitReached'] is not False or cd['spinPrizeOaks']!=[]:return False
    zeros=('freeSpinsAwarded','freeSpins','accumulatedFreeSpinWonAmount','coinWinAdjustedToMaxWinCap','gambleProbability')
    if not all(_number(cd[k]) and Decimal(str(cd[k]))==0 for k in zeros):return False
    win=cd['win'];money={'wonCoins','wonCash','accumulatedWonCoins','accumulatedWonCash','accumulatedRoundWonCoins','accumulatedRoundWonCash'}
    return isinstance(win,dict) and set(win)==money|{'prizes'} and win['prizes']==[] and all(_number(win[k]) and Decimal(str(win[k]))==0 for k in money)

def ordinary_board_metadata(cd):
    core={'win','initialBoard','finalBoard'}
    progress=core|{'wildsPositions','playerStateBefore','playerStateAfter'}
    triggered=core|{'ragnarokFeatureFrontEndData'}
    blocks=core|{'gigablox','wildsToExpand','goldenBet','extraCoinWin'}
    if not isinstance(cd,dict) or set(cd) not in (progress,triggered,blocks):return False
    if set(cd)==progress:
        if cd['wildsPositions']!=[] or cd['playerStateBefore']!={'bonusProgress':{}} or cd['playerStateAfter']!={'bonusProgress':{}}:return False
    elif set(cd)==triggered:
        if cd['ragnarokFeatureFrontEndData']!={'teaserTriggered':False,'featureTriggered':False}:return False
        # Reject integer false aliases in declared boolean flags.
        if not all(type(v) is bool for v in cd['ragnarokFeatureFrontEndData'].values()):return False
    else:
        if cd['wildsToExpand']!=[] or cd['goldenBet'] is not False or not _number(cd['extraCoinWin']) or Decimal(str(cd['extraCoinWin']))!=0:return False
        board=cd['finalBoard'];items=cd['gigablox']
        if not _board(board) or not isinstance(items,list) or not 1<=len(items)<=20:return False
        columns=[]
        for item in items:
            if not isinstance(item,dict) or set(item)!={'columns','details','blockStartRowIndex'}:return False
            cols=item['columns'];detail=item['details'];start=item['blockStartRowIndex']
            if not isinstance(cols,list) or not cols or not all(type(c) is int and 0<=c<len(board) for c in cols) or len(set(cols))!=len(cols) or type(start) is not int or not -len(board[0])<=start<len(board[0]):return False
            if not isinstance(detail,dict) or set(detail)!={'reelSetName','reelIndexFromReelSet','reelStopPosition'} or not isinstance(detail['reelSetName'],str) or not detail['reelSetName'] or type(detail['reelIndexFromReelSet']) is not int or detail['reelIndexFromReelSet'] not in cols or type(detail['reelStopPosition']) is not int or detail['reelStopPosition']<0:return False
            columns.extend(cols)
        if len(columns)!=len(set(columns)) or set(columns)!=set(range(len(board))):return False
    return ordinary_board_win({k:cd[k] for k in core})

def ordinary_closed_flags(cd):
    legacy={'GoldenBet','BuyBonus','debug','reelId','initialBoard','finalBoard','win'}
    numeric={'leftMultiplier','rightMultiplier','isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive','gambleAwarded','freeSpinsAwarded','isWinCapped','nextLeftIncrement','nextRightIncrement','version','name','stake','totalStake','currentWinnings','totalWinnings','baseGameWinnings','currentAction','nextActions','finished','reelId','initialGrid','finalGrid','wins'}
    if not isinstance(cd,dict):return False
    if set(cd)==legacy:
        if cd['GoldenBet'] is not False or cd['BuyBonus'] is not False or cd['debug']!='BG - INITIAL' or cd['reelId']!='BaseReel':return False
        win=cd['win'];extras={'accumulatedAvalancheWonCash','accumulatedAvalancheWonCoins'}
        if not isinstance(win,dict) or not extras<=set(win) or not all(_number(win[k]) and Decimal(str(win[k]))==0 for k in extras):return False
        return ordinary_board_win({k:cd[k] for k in ('initialBoard','finalBoard')}|{'win':{k:v for k,v in win.items() if k not in extras}})
    if set(cd)!=numeric or cd['finished'] is not True or cd['currentAction']!='Spin' or cd['nextActions']!=['Spin'] or cd['reelId']!='BaseGame' or cd['wins']!=[]:return False
    flags={'isGoldenBetActive','isBuyBonusActive','isSuperBuyBonusActive','gambleAwarded','isWinCapped'}
    if any(cd[k] is not False for k in flags) or not _number(cd['freeSpinsAwarded']) or Decimal(str(cd['freeSpinsAwarded']))!=0:return False
    from .enum_outcomes import _grid
    if not _grid(cd['initialGrid']) or not _grid(cd['finalGrid']) or [len(c) for c in cd['initialGrid']]!=[len(c) for c in cd['finalGrid']]:return False
    if not all(isinstance(cd[k],str) and 1<=len(cd[k])<=128 for k in ('version','name')):return False
    if not all(_number(cd[k],positive=True) for k in ('leftMultiplier','rightMultiplier','stake','totalStake')) or not all(_number(cd[k]) for k in ('nextLeftIncrement','nextRightIncrement')):return False
    return all(_number(cd[k]) and Decimal(str(cd[k]))==0 for k in ('currentWinnings','totalWinnings','baseGameWinnings'))

def ordinary_variable_heights(cd):
    keys={'win','reels','initialBoard','finalBoard','initialReelsHeight','finalReelsHeight','filledBoard','reelsOrder','freeSpinsAwarded'}
    if not isinstance(cd,dict) or set(cd)!=keys or type(cd['freeSpinsAwarded']) is not int or cd['freeSpinsAwarded']!=0:return False
    initial=cd['initialReelsHeight'];final=cd['finalReelsHeight']
    if not isinstance(initial,list) or not isinstance(final,list) or not 1<=len(initial)<=20 or initial!=final or not all(type(v) is int and 1<=v<=64 for v in initial+final):return False
    width=len(initial);height=max(initial);projected={}
    for name in ('initialBoard','finalBoard'):
        board=cd[name]
        if not isinstance(board,list) or len(board)!=width:return False
        projected[name]=[]
        for col,count in zip(board,initial):
            if not isinstance(col,list) or len(col)!=height or not all(isinstance(v,str) and 1<=len(v)<=128 for v in col[:count]) or any(v!='' for v in col[count:]):return False
            projected[name].append(col[:count]+['<inactive>']*(height-count))
    filled=cd['filledBoard']
    if not _board(filled) or len(filled)!=width or len({len(col)for col in filled})!=1 or len(filled[0])<height:return False
    order=cd['reelsOrder']
    if not isinstance(order,list) or len(order)!=width or not all(type(v) is int for v in order) or sorted(order)!=list(range(width)):return False
    reels=cd['reels']
    import re
    if not isinstance(reels,dict) or not isinstance(reels.get('reelSetName'),str) or not re.fullmatch(r'base[0-9]+_[0-9]+',reels['reelSetName']):return False
    if not ordinary_no_award({'win':cd['win'],'reels':reels,**projected,'freeSpinsAwarded':0}):return False
    return all(pos['y']<final[pos['x']] for prize in cd['win']['prizes'] for pos in prize['positions'])


def ordinary_neutral_board_multiplier(cd):
    import re
    keys={'win','reels','initialBoard','finalBoard','multiplier','winPositions'}
    if not isinstance(cd,dict) or set(cd)!=keys or not _number(cd['multiplier']) or Decimal(str(cd['multiplier']))!=1 or cd['winPositions']!=[]:return False
    reels=cd['reels']
    if not isinstance(reels,dict) or not isinstance(reels.get('reelSetName'),str) or not re.fullmatch(r'baseReels[0-9]+',reels['reelSetName']):return False
    win=cd['win'];money={'wonCoins','wonCash','accumulatedWonCoins','accumulatedWonCash','accumulatedRoundWonCoins','accumulatedRoundWonCash'}
    if not isinstance(win,dict) or set(win)!=money|{'prizes'} or win['prizes']!=[] or any(not _number(win[k]) or Decimal(str(win[k]))!=0 for k in money):return False
    return ordinary_board_win({k:cd[k] for k in ('win','reels','initialBoard','finalBoard')})
