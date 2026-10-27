"""Known neutral collection and geometry metadata; awards remain unsupported."""
from decimal import Decimal
from .named_actions import _number

def neutral_walking_state(ed):
    fields={'city','walkingBefore','walkingAfter','walkingNew'}
    return (isinstance(ed,dict) and fields<=set(ed)
            and isinstance(ed['city'],str) and 1<=len(ed['city'])<=128
            and all(ed[k]==[] for k in ('walkingBefore','walkingAfter','walkingNew'))
            and ('reSpins' not in ed or ed['reSpins'] is False))

def consume_metadata(ed,core,constraints=None):
    core=set(core);board=ed['reels'];width=len(board)
    base_wild_maps={'thisWilds','addedWilds','nextWilds'}
    if core & base_wild_maps:
        if not base_wild_maps<=core or any(not isinstance(ed[key],dict) or ed[key] for key in base_wild_maps):return None
        core-=base_wild_maps
    if core & {'currentSeason','numberOfSpins'}:
        from .seasonal_state import neutral as neutral_season
        if not neutral_season(ed,constraints):return None
        core-={'currentSeason','numberOfSpins'}
        if 'multiplier' in core:
            from .classic_wire import classic_win
            if ed['currentSeason']!='FALL' or not _number(ed['multiplier'],positive=True):return None
            coin=(constraints or {}).get('basic_coin');wins=ed.get('wtw');cells=sum(map(len,board))
            if not _number(coin,positive=True) or not isinstance(wins,list) or len(wins)>256 or any(not classic_win(v,cells) or len(v)!=3 for v in wins):return None
            if not all(_number(ed.get(k)) for k in ('wonCoins','accC','accWa')):return None
            won=sum((Decimal(str(v[1])) for v in wins),Decimal(0))
            if Decimal(str(ed['wonCoins']))!=won or Decimal(str(ed['accC']))!=won or Decimal(str(ed['accWa']))!=won*Decimal(str(coin)):return None
            core.remove('multiplier')
    from .direct_cup import consume as consume_cup
    core=consume_cup(ed,core,constraints)
    if core is None:return None
    walking={'city','walkingBefore','walkingAfter','walkingNew'}
    if core & walking:
        if not neutral_walking_state(ed):return None
        core-=walking
        if 'reSpins' in core:core.remove('reSpins')
    from .classic_geometry import consume_geometry
    core=consume_geometry(ed,core)
    if core is None:return None
    if core & {'gameState','previousGameState'}:
        from .classic_geometry import neutral_level_progress
        if not neutral_level_progress(ed):return None
        core-={'gameState','previousGameState'}
    if 'blox' in core:
        from .classic_geometry import rectangular_symbol
        if not rectangular_symbol(ed):return None
        core.remove('blox')
    if 'replaceIcons' in core:
        from .classic_geometry import symbol_replacement
        if not symbol_replacement(ed):return None
        core.remove('replaceIcons')
    if 'shardCounter' in core:
        counter=ed['shardCounter']
        if not isinstance(counter,dict) or set(counter)!={'count','c','a'}:return None
        counts=counter['count']
        if not isinstance(counts,list) or not 1<=len(counts)<=64 or not all(type(v) is int and v==0 for v in counts):return None
        size=len(counts)
        for key in ('c','a'):
            grid=counter[key]
            if not isinstance(grid,list) or len(grid)!=size or not all(isinstance(col,list) and len(col)==size and all(v is None for v in col) for col in grid):return None
        prices={prefix+str(i) for prefix in ('jpValue','jpPlayerValue') for i in range(1,size+1)}
        if not prices<=core or any(not _number(ed[k],positive=True) for k in prices):return None
        if any(ed[k]!=ed[k.replace('jpPlayerValue','jpValue')] for k in prices if k.startswith('jpPlayerValue')):return None
        core-=prices|{'shardCounter'}
    if 'splitFields' in core:
        from .classic_geometry import split_field_geometry
        if not split_field_geometry(ed):return None
        core.remove('splitFields')
    if 'allBonusAmountsInMoney' in core:
        import re
        amounts=ed['allBonusAmountsInMoney']
        if not isinstance(amounts,dict) or not 1<=len(amounts)<=64 or not all(isinstance(k,str) and re.fullmatch(r'BONUS[1-9][0-9]*',k) and _number(v,positive=True) for k,v in amounts.items()):return None
        core.remove('allBonusAmountsInMoney')
    if 'spinData' in core:
        from .classic_geometry import neutral_jackpot_features
        if neutral_jackpot_features(ed):core.remove('spinData')
    def zero(v):return _number(v) and Decimal(str(v))==0
    def position(v,extra=()):return isinstance(v,dict) and set(v)=={'x','y'}|set(extra) and type(v['x']) is int and type(v['y']) is int and 0<=v['x']<width and 0<=v['y']<len(board[v['x']])
    if core & {'doubleAmount','doubleCount'}:
        if not {'doubleAmount','doubleCount'}<=core or type(ed['doubleCount']) is not int or ed['doubleCount'] not in (0,1) or not _number(ed['doubleAmount']) or not _number(ed.get('accWa')) or Decimal(str(ed['doubleAmount']))!=Decimal(str(ed['accWa'])):return None
        core-={'doubleAmount','doubleCount'}
    if 'superBet' in core:
        if ed['superBet'] is not False:return None
        core.remove('superBet')
    sticky_mode={'penguinMode','emperorShift','previousEmperorShift','newWildCount','preStickyWilds','postStickyWilds'}
    if core & sticky_mode:
        if not sticky_mode<=core or ed['penguinMode'] is not False:return None
        if any(type(ed[k]) is not int or ed[k]!=0 for k in ('emperorShift','previousEmperorShift','newWildCount')):return None
        if ed['preStickyWilds']!=[] or ed['postStickyWilds']!=[]:return None
        core-=sticky_mode
        if 'penguinAction' in core:
            if ed['penguinAction'] is not False:return None
            core.remove('penguinAction')
    if 'collectionMeter' in core:
        capacity=(constraints or {}).get('collection_capacity')
        meter=ed['collectionMeter']
        if not isinstance(capacity,list) or len(capacity)!=width or any(type(v) is not int or not 1<=v<=64 for v in capacity):return None
        if not isinstance(meter,dict) or set(meter)!={'amounts','values'}:return None
        amounts=meter['amounts'];values=meter['values']
        if not isinstance(amounts,list) or not isinstance(values,list) or len(amounts)!=width or len(values)!=width:return None
        for amount,stored,limit in zip(amounts,values,capacity):
            if type(amount) is not int or not 0<=amount<limit or not isinstance(stored,list) or len(stored)!=amount or not all(_number(v) for v in stored):return None
        core.remove('collectionMeter')
    if 'finalReels' in core:
        from .named_actions import _board
        if not _board(ed['finalReels']) or [len(col) for col in ed['finalReels']]!=[len(col) for col in board]:return None
        core.remove('finalReels')
    inactive={'awardFromTwoScatters','goldenbet','initialFreeSpins','multiplierPositions','randomWilds','remainingFeatures','roundFeatures','spinFeatures','iconMapping'}
    if core & inactive:
        if not inactive<=core or ed['awardFromTwoScatters'] is not None or ed['goldenbet'] is not False or type(ed['initialFreeSpins']) is not int or ed['initialFreeSpins']!=0:return None
        if any(ed[k]!=[] for k in ('multiplierPositions','randomWilds','remainingFeatures','roundFeatures','spinFeatures')):return None
        mapping=ed['iconMapping']
        if not isinstance(mapping,dict) or not 1<=len(mapping)<=256 or not all(isinstance(k,str) and 1<=len(k)<=128 and v==k for k,v in mapping.items()):return None
        core-=inactive
    heads={'ReelSetConfig','blueHeadsAfter','blueHeadsBefore','fsBetAmount','redHeadsAfter','redHeadsBefore','totalblue','totalred'}
    if core & heads:
        if not heads<=core or ed['fsBetAmount'] is not None or any(type(ed[k]) is not int or ed[k]!=0 for k in heads-{'ReelSetConfig','fsBetAmount'}):return None
        config=ed['ReelSetConfig']
        if not isinstance(config,list) or len(config)!=width or not all(type(v) is int for v in config) or sorted(config)!=list(range(1,width+1)):return None
        core-=heads
    jackpots={'accWaWithJackpot','betAmountCache','jackpot'}
    if core & jackpots:
        context=constraints or {};jackpot=ed.get('jackpot')
        if not jackpots<=core or not zero(ed['accWaWithJackpot']) or not zero(ed.get('accWa')) or not zero(ed.get('wonCoins')) or ed.get('wtw')!=[]:return None
        if not isinstance(jackpot,dict) or set(jackpot)!={'miniJackpot','mediumJackpot','ultraJackpot','currency'} or jackpot['currency']!=context.get('currency') or not all(_number(jackpot[k]) for k in ('miniJackpot','mediumJackpot','ultraJackpot')):return None
        if not _number(ed['betAmountCache'],positive=True) or not _number(context.get('basic_amount'),positive=True) or Decimal(str(ed['betAmountCache']))!=Decimal(str(context['basic_amount'])):return None
        core-=jackpots
    nudges={'allEvilNudgesBaseGame','allGoodNudgesBaseGame','clashedColumns','evilNudgesBaseGame','goodNudgesBaseGame','naturallyNudgedColumnsFromEvilMachine','naturallyNudgedColumnsFromGoodMachine','newEvilWildColumnsBaseGame','newGoodWildColumnsBaseGame','notNudgedColumnsFromEvilMachine','notNudgedColumnsFromGoodMachine'}
    machine=nudges|{'noNewReSpinsBaseGame','featuresUsed'}
    if core & nudges or 'noNewReSpinsBaseGame' in core:
        if not machine<=core or ed['noNewReSpinsBaseGame'] is not True or ed['featuresUsed']!=[] or not all(ed[k]==[] for k in nudges):return None
        core-=machine
    blocking={'block','coinsBeforeMultiplier','extraLife','extraLifeCollection','multiplier','multiplierCollection','scarabsToBlocks','scarabsToExtraLife','scarabsToMultiplier','waysToWin'}
    if core & {'scarabsToBlocks','scarabsToExtraLife','scarabsToMultiplier'}:
        if not blocking<=core or not all(ed[k]==[] for k in ('scarabsToBlocks','scarabsToExtraLife','scarabsToMultiplier')) or not all(zero(ed[k]) for k in ('coinsBeforeMultiplier','extraLife','extraLifeCollection','multiplierCollection')):return None
        if not _number(ed['multiplier'],positive=True) or type(ed['waysToWin']) is not int or ed['waysToWin']<=0 or not isinstance(ed['block'],str) or len(ed['block'])!=sum(map(len,board)) or not set(ed['block'])<={'0','1'}:return None
        core-=blocking
    # A neutral sticky-column counter: no accumulated award, no multiplier mode.
    if {'grandTotal','multiplier'}<=core:
        if not zero(ed['grandTotal']) or not _number(ed['multiplier']) or Decimal(str(ed['multiplier']))!=1 or not zero(ed.get('wonCoins')) or ed.get('wtw')!=[]:return None
        core-={'grandTotal','multiplier'}
    if 'coinsBeforeMultiplier' in core:
        if not zero(ed['coinsBeforeMultiplier']):return None
        core.remove('coinsBeforeMultiplier')
    if core & {'stickyA','stickyB','stickyN'}:
        fields={'stickyA','stickyB','stickyN'}
        if not fields<=core or not all(isinstance(ed[k],str) and len(ed[k])==sum(map(len,board)) and set(ed[k])=={'0'} for k in fields):return None
        core-=fields
    if core & {'multipliers','pumpkinsAmount'}:
        if not {'multipliers','pumpkinsAmount'}<=core or not zero(ed['pumpkinsAmount']):return None
        m=ed['multipliers']
        if not isinstance(m,dict) or not 1<=len(m)<=256 or not all(isinstance(k,str) and k and _number(v,positive=True) for k,v in m.items()):return None
        core-={'multipliers','pumpkinsAmount'}
    fields={'collectionBefore','collectionAfter','newCollectionItemsRow','newItems'}
    if core & fields:
        if not fields<=core or ed['newCollectionItemsRow']!=[] or ed['newItems']!=['']*width:return None
        for k in ('collectionBefore','collectionAfter'):
            m=ed[k]
            if not isinstance(m,dict) or set(m)!={f'Reel{i}' for i in range(width)} or not all(v==['',''] for v in m.values()):return None
        core-=fields
    fields={'avgCoinValueMap','defeatedDemons','gameLevel','rageStatus'}
    if core & fields:
        if not fields<=core or not zero(ed['defeatedDemons']) or not zero(ed['gameLevel']):return None
        avg=ed['avgCoinValueMap'];status=ed['rageStatus']
        if not isinstance(avg,dict) or not 1<=len(avg)<=256 or not all(isinstance(k,str) and k and _number(v) for k,v in avg.items()) or not isinstance(status,dict) or set(status)!={'before','after'}:return None
        trigger=(constraints or {}).get('rage_trigger')
        if not _number(trigger,positive=True):return None
        before=status['before'];after=status['after']
        if not isinstance(before,dict) or before!=after or set(before)!=set(avg):return None
        for item in before.values():
            if not isinstance(item,dict) or set(item)!={'rage'} or not _number(item['rage']) or not 0<=Decimal(str(item['rage']))<Decimal(str(trigger)):return None
        core-=fields
    fields={'bonusMoneyWon','reelsPermutation','splitzContainers','totalWaysAmount'}
    if core & fields:
        if not fields<=core or not zero(ed['bonusMoneyWon']) or ed['splitzContainers']!=[]:return None
        perm=ed['reelsPermutation'];ways=ed['totalWaysAmount']
        if not isinstance(perm,list) or not all(type(v) is int for v in perm) or sorted(perm)!=list(range(width)) or type(ways) is not int or ways<=0:return None
        core-=fields
    fields={'blockers','connectBonus','tokens'}
    if core & fields:
        if not fields<=core or ed['tokens']!=[]:return None
        blockers=ed['blockers'];connect=ed['connectBonus']
        if not isinstance(blockers,dict) or set(blockers)!={'initialBlockers','removals'} or blockers['removals']!=[]:return None
        initial=blockers['initialBlockers']
        if not isinstance(initial,list) or len(initial)>1280 or not all(position(v) for v in initial):return None
        if not isinstance(connect,list) or len(connect)>1280 or not all(position(v,('newSymbol',)) and isinstance(v['newSymbol'],str) and v['newSymbol'] for v in connect):return None
        core-=fields
    fields={'currentMode','scattersInfo','sticky'}
    if core & fields:
        if not fields<=core or ed['currentMode']!='SPIN' or ed['scattersInfo']!={'totalNumberOfScatters':0,'positionsOfNewScatters':[]}:return None
        sticky=ed['sticky']
        if not isinstance(sticky,str) or len(sticky)!=sum(map(len,board)) or set(sticky)!={'0'}:return None
        core-=fields
    return core
