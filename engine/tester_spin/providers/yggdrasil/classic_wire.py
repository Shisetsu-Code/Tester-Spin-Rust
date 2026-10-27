"""Classic echoed line wagers and flat ordinary outcomes."""
from decimal import Decimal,InvalidOperation
import re
from .named_actions import _number,_board

def _financial_echo(bd):
    if not isinstance(bd,dict):return None
    if 'cmds' not in bd:return bd
    from .protocol import command_values
    if command_values(bd['cmds']) not in ([],['C']):return None
    return {k:v for k,v in bd.items() if k!='cmds'}


def echoed_base_bet(root,template,currency="EUR",classic_line_quantity=False):
    if root.get("betcurrency")!=currency:return False
    bd=_financial_echo(root.get('betdata'))
    if not isinstance(bd,dict):return False
    if classic_line_quantity:
        keys={'lines','coin','nCoins','cheat','clientData'}
        if set(bd) not in (keys,keys|{'initialBalance'}) or bd['cheat'] is not None or bd['clientData'] is not None:return False
        if 'initialBalance' in bd and not _number(bd['initialBalance']):return False
        lines=bd['lines']
        if not isinstance(lines,str) or not lines or not set(lines)<={'0','1'} or lines!=template.get('lines'):return False
        try:
            coins=Decimal(str(bd['nCoins']));coin=Decimal(str(bd['coin']));count=lines.count('1')
            return coins==1 and coin==Decimal(str(template['coin'])) and count==Decimal(str(template['coins'])) and coin*coins*count==Decimal(str(root['betamount']))==Decimal(str(template['amount']))
        except (InvalidOperation,ValueError,KeyError,TypeError):return False
    if set(bd) in ({'coin','cmd','ncoins','accWa','accC'},{'coin','cmd','ncoins','accWa','accC','initialBalance'}):
        if 'initialBalance' in bd and not _number(bd['initialBalance']):return False
        if bd['cmd']!='' or not all(_number(bd[k]) for k in ('accWa','accC')):return False
        try:return Decimal(str(bd['coin']))==Decimal(str(template['coin'])) and Decimal(str(bd['ncoins']))==Decimal(str(template['coins'])) and Decimal(str(root['betamount']))==Decimal(str(template['amount']))
        except (InvalidOperation,ValueError,KeyError,TypeError):return False
    if set(bd)!={'lines','coin','nCoins','cheat','clientData','initialBalance'}:return False
    if bd['cheat'] is not None or bd['clientData'] is not None or bd['lines']!=template.get('lines'):return False
    if not _number(bd['initialBalance']):return False
    try:return Decimal(str(bd['coin']))==Decimal(str(template['coin'])) and Decimal(str(bd['nCoins']))==Decimal(str(template['coins'])) and Decimal(str(root['betamount']))==Decimal(str(template['amount']))
    except (InvalidOperation,ValueError,KeyError,TypeError):return False

def _collection(v):
    if not isinstance(v,dict) or set(v)!={'amount','hasSeen','averageCoin'}:return False
    arrays=list(v.values())
    if not all(isinstance(x,list) for x in arrays) or not 1<=len(v['amount'])<=256 or len({len(x) for x in arrays})!=1:return False
    return all(_number(x) for x in v['amount']+v['averageCoin']) and all(type(x) is bool for x in v['hasSeen'])

def classic_win(win,cells):
    # Legacy line/ways vectors observed in server outcomes. The mask is tied
    # to the current board; extra command or award data is not a win vector.
    if not isinstance(win,list) or len(win) not in (3,5,6):return False
    if type(win[0]) is not int or win[0]<0 or type(win[1]) is not int or win[1]<0:return False
    if not isinstance(win[2],str) or len(win[2])!=cells or not set(win[2])<={'0','1'} or '1' not in win[2]:return False
    if len(win)==3:return True
    if not _number(win[3]):return False
    if isinstance(win[4],dict):
        ways=win[4]
        if len(win)!=5 or set(ways)!={'waysAmount','oakIndex','coinsPerWay','cashPerWay','icon'}:return False
        return all(type(ways[k]) is int and ways[k]>0 for k in ('waysAmount','oakIndex','coinsPerWay')) and _number(ways['cashPerWay']) and isinstance(ways['icon'],str) and 1<=len(ways['icon'])<=128
    return _number(win[4]) and (len(win)==5 or _number(win[5]))


def ordinary_flat_event(ed,constraints=None):
    if isinstance(ed,dict) and 'nextCmds' in ed:
        from .protocol import command_values
        if command_values(ed['nextCmds']) not in ([],['C'],['C','*']):return False
        ed={k:v for k,v in ed.items() if k!='nextCmds'}
    if isinstance(ed,dict) and {'blockers','connectBonus','tokens','reels','finalBoard'}<=set(ed):
        boards=[]
        for key in ('reels','finalBoard'):
            board=ed[key]
            if not isinstance(board,list) or not 1<=len(board)<=20:return False
            for col in board:
                if not isinstance(col,list) or not 1<=len(col)<=64 or not all(isinstance(v,str) and len(v)<=128 for v in col) or not col[0]:return False
                first=next((i for i,v in enumerate(col) if v==''),len(col))
                if any(v!='' for v in col[first:]):return False
            boards.append(board)
        if [len(col) for col in boards[0]]!=[len(col) for col in boards[1]] or [[v=='' for v in col] for col in boards[0]]!=[[v=='' for v in col] for col in boards[1]]:return False
        # Only this declared blockers geometry uses trailing non-playable cells.
        # Substitute locally for the shared geometry validator, retaining raw DTOs.
        ed={**ed,**{key:[[v or '<padding>' for v in col] for col in ed[key]] for key in ('reels','finalBoard')}}
    if isinstance(ed,dict) and 'wonAmount' in ed and 'wonCash' not in ed and 'wonMoney' not in ed:ed={('wonCash' if k=='wonAmount' else k):v for k,v in ed.items()}
    if isinstance(ed,dict) and 'wonMoney' in ed and 'wonCash' not in ed:ed={('wonCash' if k=='wonMoney' else k):v for k,v in ed.items()}
    if isinstance(ed,dict) and not {'wonMoney','wonAmount','wonCash'}&set(ed) and _number(ed.get('wonCoins')) and Decimal(str(ed['wonCoins']))==0 and ed.get('wtw')==[]:ed={**ed,'wonCash':0}
    if isinstance(ed,dict) and not {'wonMoney','wonAmount','wonCash'}&set(ed):
        coin=(constraints or {}).get('basic_coin')
        if _number(coin,positive=True) and all(_number(ed.get(k)) for k in ('wonCoins','accC','accWa')) and Decimal(str(ed['accC']))==Decimal(str(ed['wonCoins'])) and Decimal(str(ed['accWa']))==Decimal(str(ed['wonCoins']))*Decimal(str(coin)):
            ed={**ed,'wonCash':ed['accWa']}
    from .classic_geometry import neutral_level_progress, rectangular_symbol, neutral_jackpot_features
    level_progress=isinstance(ed,dict) and neutral_level_progress(ed)
    block_geometry=isinstance(ed,dict) and rectangular_symbol(ed)
    from .classic_metadata import neutral_walking_state
    from .seasonal_state import neutral as neutral_season
    required={'accC','accWa','reelSet','reels','rpos','wonCash','wonCoins','wts','wtw'}
    if isinstance(ed,dict) and 'wts' not in ed:required.remove('wts')
    if not isinstance(ed,dict) or not required<=set(ed) or not (ed['reelSet']=='Reels' or neutral_season(ed,constraints) or ed['reelSet']=='ReelsShiftingWild' and neutral_walking_state(ed) or ed['reelSet']=='Base' and neutral_jackpot_features(ed) or block_geometry and isinstance(ed['reelSet'],str) and ed['reelSet'] in {'Reels12','Reels34'} or level_progress and isinstance(ed['reelSet'],str) and re.fullmatch(r'Reels[2-5]',ed['reelSet']) or isinstance(ed['reelSet'],str) and re.fullmatch(r'(?:BaseReel|BaseReels[0-9]*|BaseReels(?:_[0-9]+)+|Base_[0-9]+|BaseGameReels|BaseReels(?:Left|Right)|ReelsSet[A-Z]|Reels[A-Z])',ed['reelSet']) or isinstance(ed['reelSet'],str) and 'ReelSetConfig' in ed and re.fullmatch(r'ReelsConfig[1-9][0-9]*',ed['reelSet']) or isinstance(ed['reelSet'],str) and (('noNewReSpinsBaseGame' in ed and re.fullmatch(r'M[0-9]+(?:,M[0-9]+)*',ed['reelSet'])) or ('scarabsToBlocks' in ed and re.fullmatch(r'R[0-9]+(?:,R[0-9]+)*',ed['reelSet'])))):return False
    if not _board(ed['reels']):return False
    from .classic_metadata import consume_metadata
    core=consume_metadata(ed,set(ed)-required,constraints)
    if core is None:return False
    if 'featuresUsed' in core:
        features=ed['featuresUsed']
        if not isinstance(features,list) or not 1<=len(features)<=256 or not all(v=='noFeature' for v in features):return False
        core.remove('featuresUsed')
    if core & {'scatterWonExtraCoins','scatterWonExtraMoney'}:
        fields={'scatterWonExtraCoins','scatterWonExtraMoney'}
        if not fields<=core or not all(_number(ed[k]) for k in fields):return False
        core-=fields
    if 'multiplierValue' in core:
        if not _number(ed['multiplierValue'],positive=True):return False
        core.remove('multiplierValue')
    if 'scatterReplacingIcon' in core:
        if not isinstance(ed['scatterReplacingIcon'],str) or not 1<=len(ed['scatterReplacingIcon'])<=128:return False
        core.remove('scatterReplacingIcon')
    progress_pairs=[('gloryBeforeSpin','gloryAfterSpin'),('experienceBeforeSpin','experienceAfterSpin')]
    for before,after in progress_pairs:
        if core & {before,after}:
            if not {before,after}<=core:return False
            maps=[ed[before],ed[after]]
            if not all(isinstance(m,dict) and 1<=len(m)<=256 for m in maps) or set(maps[0])!=set(maps[1]):return False
            for m in maps:
                for name,item in m.items():
                    if not isinstance(name,str) or not name or not isinstance(item,dict) or set(item)!={'amount','gathered','coinsSum'} or not all(_number(v) for v in item.values()) or Decimal(str(item['gathered']))!=0:return False
            core-={before,after}
    if core & {'baseWonCoins','jackpotInfo','reelsPositionsAfterNudge'}:
        if not {'baseWonCoins','jackpotInfo','reelsPositionsAfterNudge'}<=core or not _number(ed['baseWonCoins']):return False
        info=ed['jackpotInfo'];stops=ed['reelsPositionsAfterNudge']
        if not isinstance(info,dict) or set(info)!={'secondsToGuaranteedFallout','jackpotValue','clockIsTicking','operatorHasDailyJackpot'} or info['clockIsTicking'] is not False or type(info['operatorHasDailyJackpot']) is not bool or not all(_number(info[k]) for k in ('secondsToGuaranteedFallout','jackpotValue')):return False
        if not isinstance(stops,list) or len(stops)!=len(ed['reels']) or not all(type(v) is int and v>=0 for v in stops):return False
        core-={'baseWonCoins','jackpotInfo','reelsPositionsAfterNudge'}
    if core & {'usedReels','syncReelsCount'}:
        if not {'usedReels','syncReelsCount'}<=core:return False
        used=ed['usedReels'];count=ed['syncReelsCount']
        if not isinstance(used,list) or len(used)!=len(ed['reels']) or not all(type(v) is int and 0<=v<20 for v in used) or len(set(used))!=len(used) or type(count) is not int or not 1<=count<=len(used):return False
        core-={'usedReels','syncReelsCount'}
    if core & {'coinsAccd','currentSticky','grandTotal','jpPlayerValue'}:
        fields={'coinsAccd','currentSticky','grandTotal','jpPlayerValue'}
        if not fields<=core or not all(_number(ed[k]) for k in fields) or any(Decimal(str(ed[k]))!=0 for k in ('coinsAccd','currentSticky','grandTotal')):return False
        core-=fields
    if core & {'baseGameCoins','notStackedIndex'}:
        if not {'baseGameCoins','notStackedIndex'}<=core or not _number(ed['baseGameCoins']) or type(ed['notStackedIndex']) is not int or not 0<=ed['notStackedIndex']<len(ed['reels']):return False
        core-={'baseGameCoins','notStackedIndex'}
    if core & {'blockDetails','reelDetails'}:
        if not {'blockDetails','reelDetails'}<=core:return False
        width=len(ed['reels']);height=max(map(len,ed['reels']))
        blocks=ed['blockDetails'];details=ed['reelDetails']
        if not isinstance(blocks,list) or len(blocks)>20 or not isinstance(details,dict) or set(details)!={str(i) for i in range(width)}:return False
        for detail in details.values():
            if not isinstance(detail,dict) or set(detail)!={'reelIndex','reelName'} or type(detail['reelIndex']) is not int or not 0<=detail['reelIndex']<width or not isinstance(detail['reelName'],str) or not re.fullmatch(r'base[0-9]*Reels[0-9]*',detail['reelName']):return False
        for block in blocks:
            if not isinstance(block,dict):return False
            if set(block)=={'startRow','reelIndex','blockSize'}:
                size,row,reel=(block[k] for k in ('blockSize','startRow','reelIndex'))
            elif set(block)=={'startRowIndex','startReelIndex','size','symbol'} and isinstance(block['symbol'],str) and block['symbol']:
                size=block['size'];row=block['startRowIndex'];reel=block['startReelIndex']
            else:return False
            if any(type(x) is not int for x in (size,row,reel)) or not 1<=size<=min(width,height) or not -size<row<height or not 0<=reel<=width-size:return False
        core-={'blockDetails','reelDetails'}
    if 'spinName' in core:
        if not isinstance(ed['spinName'],str) or not re.fullmatch(r'[A-Za-z0-9]+BaseGameSpin',ed['spinName']):return False
        core.remove('spinName')
    collection_keys={'collections','previousCollections','averageCoinValue'}
    if core & collection_keys:
        if not collection_keys<=core:return False
        for key in ('collections','previousCollections'):
            value=ed[key]
            if not isinstance(value,dict) or set(value)!={'collectibles','userWonFreespins'} or value['userWonFreespins'] is not False:return False
            items=value['collectibles']
            if not isinstance(items,dict) or not 1<=len(items)<=256:return False
            for item in items.values():
                if not isinstance(item,dict) or set(item)!={'amount','gathered','coinsSum','bets'} or item['bets']!=[] or not all(_number(item[k]) for k in ('amount','gathered','coinsSum')):return False
        avg=ed['averageCoinValue']
        if not isinstance(avg,dict) or set(avg)!=set(ed['collections']['collectibles']) or set(avg)!=set(ed['previousCollections']['collectibles']) or not all(_number(x) for x in avg.values()):return False
        core-=collection_keys
    if 'finalBoard' in core:
        if not _board(ed['finalBoard']):return False
        core.remove('finalBoard')
    if 'spinData' in core:
        data=ed['spinData']
        if not isinstance(data,dict) or set(data) not in ({'featuresOutputs','multiplier'},{'featuresOutputs'}) or 'multiplier' in data and not _number(data['multiplier'],positive=True) or not isinstance(data['featuresOutputs'],dict):return False
        if 'multiplier' not in data and data['featuresOutputs']!={}:return False
        for feature,movement in data['featuresOutputs'].items():
            if feature=='edgeScatters':
                from .edge_replacements import valid_output
                if not valid_output(ed,constraints):return False
                continue
            if not isinstance(movement,dict) or set(movement)!={'positionBefore','positionAfter'}:return False
            for pos in movement.values():
                if not isinstance(pos,dict) or set(pos)!={'reel','row'} or type(pos['reel']) is not int or type(pos['row']) is not int or not 0<=pos['reel']<len(ed['reels']) or not 0<=pos['row']<len(ed['reels'][pos['reel']]):return False
        core.remove('spinData')
    if not all(k.endswith('Collection') and _collection(ed[k]) for k in core):return False
    stop_count=len(ed['reels'])
    if 'noNewReSpinsBaseGame' in ed:
        stop_count*=2
        if len(ed['reelSet'].split(','))!=stop_count or len({len(col) for col in ed['reels']})!=1 or len(ed['reels'][0])%2:return False
    # The legacy client uses the explicit board when strip offsets are null.
    if ed['rpos'] is not None and (not isinstance(ed['rpos'],list) or len(ed['rpos'])!=stop_count or not all(type(x) is int and x>=0 for x in ed['rpos'])):return False
    if not all(_number(ed[k]) for k in ('accC','accWa','wonCash','wonCoins')):return False
    if not isinstance(ed.get('wts',[]),list) or len(ed.get('wts',[]))>256 or not all(isinstance(x,str) and 1<=len(x)<=4096 and set(x)<={'0','1'} for x in ed.get('wts',[])):return False
    return isinstance(ed['wtw'],list) and len(ed['wtw'])<=256 and all(_number(x) or classic_win(x,sum(map(len,ed['reels']))) for x in ed['wtw'])


def collected_classic_bet(before,after,request):
    try:
        prior=before['bets'][0];bd=_financial_echo(prior.get('betdata'))
        if bd is None:return False
        compact=set(bd) in ({'coin','cmd','ncoins','accWa','accC'},{'coin','cmd','ncoins','accWa','accC','initialBalance'}) and bd.get('cmd')==''
        if 'cashBet' in bd or not compact and not {'coin','nCoins','lines'}<=set(bd):return False
        bet=next((b for b in after['bets'] if b['step']==int(request['step'])),None)
        currency=prior.get('betcurrency')
        if not isinstance(currency,str) or not re.fullmatch(r'[A-Z]{3}',currency):return False
        if bet is None or request.get('cmd')!='C' or Decimal(str(bet.get('betamount')))!=0 or bet.get('betcurrency')!=currency:return False
        reply=bet.get('betdata')or{}
        counts=[reply[k] for k in ('nCoins','ncoins') if k in reply]
        if len(counts)!=1 or reply.get('cmd')!='C' or Decimal(str(reply.get('coin')))!=Decimal(str(bd['coin'])) or Decimal(str(counts[0]))!=Decimal(str(bd['ncoins'] if compact else bd['nCoins'])):return False
        if not compact:return reply.get('lines')==bd['lines']
        lines=reply.get('lines')
        return lines is None or isinstance(lines,str) and 1<=len(lines)<=4096 and set(lines)<={'0','1'}
    except (InvalidOperation,ValueError,KeyError,TypeError):return False


def ordinary_jackpot_collections(cd):
    keys={'averageCoinValue','collectionBeforeSpin','collections','finalBoard','jackpotStatus','reelSet','reels','rpos','wonCoins','wonMoney','wtw'}
    if not isinstance(cd,dict) or set(cd) not in (keys,keys|{'accC','accWa'}):return False
    domains=[]
    for field in ('collectionBeforeSpin','collections'):
        items=cd[field]
        if not isinstance(items,dict) or not 1<=len(items)<=256:return False
        domains.append(set(items))
        for item in items.values():
            if not isinstance(item,dict):return False
            if set(item)=={'amount','gathered','coinsSum','bets'}:
                if item['bets']!=[] or not all(_number(item[k]) for k in ('amount','gathered','coinsSum')):return False
            elif set(item)=={'amount','gathered','coinValuesSum','jackpotStakeValuesSum','coinValues','jackpotStakeValues'}:
                if item['coinValues']!=[] or item['jackpotStakeValues']!=[] or not all(_number(item[k]) for k in ('amount','gathered','coinValuesSum','jackpotStakeValuesSum')):return False
            else:return False
            if Decimal(str(item['gathered']))!=0:return False
    average=cd['averageCoinValue'];jackpots=cd['jackpotStatus']
    if not isinstance(average,dict) or set(average)!=domains[0] or set(average)!=domains[1] or not all(_number(v) for v in average.values()):return False
    if not isinstance(jackpots,dict) or not 1<=len(jackpots)<=256 or not all(isinstance(k,str) and k and _number(v) for k,v in jackpots.items()):return False
    core={k:cd[k] for k in ('finalBoard','reelSet','reels','rpos','wonCoins','wonMoney','wtw')}
    core.update(accC=cd.get('accC',0),accWa=cd.get('accWa',0))
    return ordinary_flat_event(core)
