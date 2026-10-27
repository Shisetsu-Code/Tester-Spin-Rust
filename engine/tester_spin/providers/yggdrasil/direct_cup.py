"""Configured coin-only chest rewards; other reward types stay unsupported."""
import re
from decimal import Decimal
from .named_actions import _number

def declaration(props):
    prizes=props.get('BaseSilverCupPrizes');weights=props.get('BaseSilverCupDistribution')
    if not isinstance(prizes,dict) or not isinstance(weights,dict) or not 1<=len(prizes)<=256 or set(prizes)!=set(weights):return None
    if any(not isinstance(k,str) or not 1<=len(k)<=128 or not _number(prizes[k],positive=True) or not _number(weights[k]) for k in prizes):return None
    coins={}
    for key,value in prizes.items():
        match=re.fullmatch(r'COINS_([1-9][0-9]{0,8})',key)
        if match:
            amount=int(match[1])
            if Decimal(str(value))!=amount:return None
            if Decimal(str(weights[key]))>0:coins[key]=amount
    return coins or None

def consume(ed,core,constraints):
    fields={'baseSilverCupWin','bonusWin','featureNames'}
    if not core&fields:return core
    if not fields<=core or ed['featureNames']!=['baseSilverCupFeature']:return None
    awards=(constraints or {}).get('cup_coin_awards');key=ed['baseSilverCupWin']
    if not isinstance(awards,dict) or not isinstance(key,str) or key not in awards:return None
    if type(awards[key]) is not int or awards[key]<=0 or not _number(ed['bonusWin']) or Decimal(str(ed['bonusWin']))!=awards[key]:return None
    coin=(constraints or {}).get('basic_coin');wins=ed.get('wtw');board=ed.get('reels')
    from .classic_wire import classic_win
    if not _number(coin,positive=True) or not isinstance(wins,list) or len(wins)>256 or not isinstance(board,list):return None
    cells=sum(map(len,board))
    if any(not classic_win(v,cells) or len(v)!=3 for v in wins):return None
    total=sum((Decimal(str(v[1])) for v in wins),Decimal(awards[key]))
    if not all(_number(ed.get(k)) for k in ('wonCoins','accC','accWa','wonCash')):return None
    if any(Decimal(str(ed[k]))!=total for k in ('wonCoins','accC')) or any(Decimal(str(ed[k]))!=total*Decimal(str(coin)) for k in ('accWa','wonCash')):return None
    return core-fields
