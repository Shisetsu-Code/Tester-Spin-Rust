"""Monetary observations and root acknowledgments, independent of state catalogs."""
from decimal import Decimal,InvalidOperation

def step_win(game,*,client_source=None):
    if client_source is not None:
        from .client_money import monetary_fields
        fields=monetary_fields(client_source)
        if fields is None:raise ValueError('Nolimit City: dialecto monetario sin declaración cliente')
        if fields['spin'] not in game:raise ValueError('Nolimit City: premio cliente ausente')
        observed={'win':game[fields['spin']]}
        if 'win' in game:observed['thisSpinWinning']=game['win']
        return step_win(observed)
    names=[key for key in ('win','thisSpinWinning','thisSpinWinnings','thisAvalancheWinnings') if key in game]
    if not names:names=['totalSpinWinnings'] if 'totalSpinWinnings' in game else []
    if not names:raise ValueError('Nolimit City: premio de paso ausente')
    values=[]
    for key in names:
        value=game[key]
        if value is None or isinstance(value,bool):raise ValueError('Nolimit City: premio de paso inválido')
        try:number=Decimal(str(value))
        except InvalidOperation:raise ValueError('Nolimit City: premio de paso inválido') from None
        if not number.is_finite():raise ValueError('Nolimit City: premio de paso no finito')
        values.append(number)
    if len(set(values))!=1:raise ValueError('Nolimit City: premios de paso contradictorios')
    return game[names[0]]

def modifier_ack(game,*,declared_selector=None):
    flags=[]
    for key in ('wasBoostedBet','boostedBet','boostedBetPlayed','enhancedBet'):
        if key not in game:continue
        value=game[key]
        if type(value) is bool:flags.append(value)
        elif key=='boostedBetPlayed' and isinstance(value,str) and declared_selector is not None and value==declared_selector:flags.append(True)
        elif key=='enhancedBet' and type(value) is int and value>=0:flags.append(value>0)
        else:raise ValueError('Nolimit City: indicador de modificador inválido: '+key)
    if len(set(flags))>1:raise ValueError('Nolimit City: indicadores de modificador contradictorios')
    return flags[0] if flags else None

def root_ack(game,mode,request,*,debit_confirmed=False):
    kind=mode['kind'];purchase=game.get('wasFeatureBuy');boost=game.get('wasBoostedBet')
    if request is not None:
        expected='normalBet' if kind=='SPIN' else 'featureBet'
        if request.get('type')!=expected or Decimal(str(request.get('bet')))!=Decimal(str(mode['stake'])):
            raise ValueError('Nolimit City: petición raíz no coincide con la apuesta declarada')
        if kind=='SPIN' and set(request)!={'type','bet'}:
            raise ValueError('Nolimit City: parámetros inesperados en giro normal')
        if kind!='SPIN' and mode.get('selector') is not None:
            selector=mode['selector']
            if request.get('featureName')!=selector or request.get('playerInteraction')!={'featureName':selector}:
                raise ValueError('Nolimit City: petición raíz sin selector declarado')
    if purchase is not None and type(purchase) is not bool:raise ValueError('Nolimit City: acuse de compra inválido')
    if kind=='PURCHASE':
        declared_debit_ack=('wasFeatureBuy' not in game and game.get('featureBet') is True
            and debit_confirmed and isinstance(request,dict) and mode.get('server_declared') is True
            and isinstance(mode.get('selector'),str) and bool(mode['selector'])
            and mode['selector'] in mode.get('declared_feature_options',())
            and mode['selector'] in mode.get('declared_purchase_options',()))
        if purchase is not True and not declared_debit_ack:raise ValueError('Nolimit City: compra no confirmada')
    elif kind=='FEATURE_SPIN':
        feature_ack=game.get('featureBet') is True and purchase is False
        debit_ack=(debit_confirmed and mode.get('server_declared') is True
            and mode.get('selector') in mode.get('declared_feature_options',())
            and mode.get('server_type') in ('BOOSTED_BET','BOOSTED_BET_X_ROWS'))
        purchase_absent_but_boost_ack=(purchase is None and boost is True and debit_ack)
        if (purchase is not False and not purchase_absent_but_boost_ack) or (boost is not True and not (boost is None and (feature_ack or debit_ack))):
            raise ValueError('Nolimit City: modificador no confirmado')
    else:
        if purchase is True or boost is True:raise ValueError('Nolimit City: giro normal con modificador inexplicado')
        if purchase is None or boost is None:
            if not isinstance(request,dict) or set(request)!={'type','bet'} or request.get('type')!='normalBet':
                raise ValueError('Nolimit City: giro normal sin petición y acuses contrastados')


def reconciled_step_win(game,previous,*,client_source=None):
    """Resolve a total-only dialect using both reported total and round accumulation."""
    total=step_win(game,client_source=client_source) if client_source is not None else step_win({'totalSpinWinnings':game.get('totalSpinWinnings')})
    accumulated=round_win(game,client_source=client_source)
    if accumulated is None or isinstance(accumulated,bool):raise ValueError('Nolimit City: acumulado ausente o inválido')
    try:current=Decimal(str(accumulated));reported=Decimal(str(total));delta=current-previous
    except InvalidOperation:raise ValueError('Nolimit City: importes inválidos') from None
    if not current.is_finite() or not reported.is_finite() or current<0 or reported<0 or delta<0:
        raise ValueError('Nolimit City: total sin contrato de descuento')
    if reported not in (delta,current):raise ValueError('Nolimit City: total no concilia con paso ni acumulado')
    return str(delta)


def row_response(game):
    return (all(key in game for key in ('freespinPlayed','freespinsLeft','playedRowsInFS','playedRowsInBase','featureBuyRows','fsSpecialSymbol','wasFeatureBuy','freespinTriggeredThisSpin'))
        and type(game['freespinPlayed']) is int and game['freespinPlayed']>=0
        and type(game['freespinsLeft']) is int and game['freespinsLeft']>=0
        and all(type(game[k]) is int and 3<=game[k]<=5 for k in ('playedRowsInFS','playedRowsInBase'))
        and type(game['featureBuyRows']) is int and game['featureBuyRows'] in (-1,3,4,5)
        and isinstance(game['fsSpecialSymbol'],str)
        and all(type(game[k]) is bool for k in ('wasFeatureBuy','freespinTriggeredThisSpin')))


def collect_available(game):
    return (game.get('nextMode')=='GAMBLE' and type(game.get('gambleCollect')) is bool
        and game['gambleCollect'] is False and isinstance(game.get('gambleOptions'),dict))


def round_win(game,*,client_source=None):
    """Read the independent round total selected by the same client parser."""
    field='accumulatedRoundWin'
    if client_source is not None:
        from .client_money import monetary_fields
        fields=monetary_fields(client_source)
        if fields is None:raise ValueError('Nolimit City: dialecto monetario sin declaración cliente')
        field=fields['round']
    if field not in game:raise ValueError('Nolimit City: acumulado cliente ausente')
    observed={'win':game[field]}
    if field!='accumulatedRoundWin' and 'accumulatedRoundWin' in game:
        observed['thisSpinWinning']=game['accumulatedRoundWin']
    return step_win(observed)


def remaining_alias(answer):
    """A remaining counter alias requires agreement with the outer server total."""
    game=answer.get('game') or {}
    left=game.get('freespinsLeft')
    if 'freespinsLeft' in game:return left
    if 'freespinsRemaining' not in game:return None
    left=game['freespinsRemaining'];outer=answer.get('remainingFreeSpins')
    if type(left) is not int or left<0 or type(outer) is not int or left!=outer:
        raise ValueError('Nolimit City: contadores restantes contradictorios')
    return left
