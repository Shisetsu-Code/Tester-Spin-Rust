"""Server-declared options and prices; no session state or execution certification."""
from decimal import Decimal
from .protocol import _money
from .errors import Unlearned
from .operation_fields import row_response as _row_response

def declared_options(init):
    game=init.get('game');config=init.get('gameClientConfiguration');allowed=init.get('allowedFeatureBets')
    levels=init.get('featureBetLevels');types=init.get('allowedFeatureTypes')
    if not isinstance(game,dict) or not isinstance(config,dict) or not isinstance(levels,dict) or not isinstance(types,list):
        raise Unlearned('Nolimit City: declaración incompleta de opciones y apuestas')
    table=game.get('featureBuyTimesBetValue')
    if table is None and allowed==[]:table=[]
    if not isinstance(table,list) or not isinstance(allowed,list) or any(not isinstance(v,str) or not v for v in allowed) or len(set(allowed))!=len(allowed):
        raise Unlearned('Nolimit City: dominio de opciones ausente o inválido')
    quotes={}
    for item in table:
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not item['name'] or item['name'] in quotes:
            raise Unlearned('Nolimit City: precio duplicado o inválido')
        quotes[item['name']]=item
    if set(allowed)-set(quotes):raise Unlearned('Nolimit City: selector permitido sin precio')
    base=(init.get('betLevels') or {}).get('availableBetLevels')
    if not isinstance(base,list) or not base:raise Unlearned('Nolimit City: dominio de apuesta normal ausente')
    stake=min(_money(v,positive=True) for v in base)
    if stake!=stake.quantize(Decimal('.01')):raise Unlearned('Nolimit City: escala de apuesta no demostrada')
    modes=[{'id':'SPIN','kind':'SPIN','stake':format(stake,'.2f'),'price_multiplier':'1',
            'required_options':['spin'],'server_declared':True}]
    for name in allowed:
        quote=quotes[name];kind={'FREESPIN':'PURCHASE','BOOSTED_BET':'FEATURE_SPIN','BOOSTED_BET_X_ROWS':'FEATURE_SPIN'}.get(quote.get('type'),'UNKNOWN_FEATURE')
        price=_money(quote.get('price'),positive=True)
        domain=levels.get(name)
        if not isinstance(domain,list) or not domain:raise Unlearned('Nolimit City: faltan apuestas permitidas para '+name)
        value=min(_money(v,positive=True) for v in domain)
        if value!=value.quantize(Decimal('.01')):raise Unlearned('Nolimit City: escala de apuesta modificada no demostrada')
        if kind=='PURCHASE' and (config.get('featureBuyEnabled') is not True or 'BONUS_BUY' not in types):
            raise Unlearned('Nolimit City: compra contradice la habilitación del servidor')
        if kind=='FEATURE_SPIN' and (config.get('boostedBetAllowed') is not True or 'BOOSTED_BET' not in types):
            raise Unlearned('Nolimit City: apuesta mejorada contradice la habilitación del servidor')
        if quote.get('type')=='BOOSTED_BET_X_ROWS' and (config.get('boostedBetExtraRows') is not True or 'BOOSTED_BET_X_ROWS' not in types):
            raise Unlearned('Nolimit City: filas mejoradas sin habilitación del servidor')
        unsupported_extra=quote.get('additionalTypes') not in (None,[])
        modes.append({'id':('BUY_' if kind=='PURCHASE' else 'BOOST_' if kind=='FEATURE_SPIN' else 'UNKNOWN_')+name,
            'kind':kind,'selector':name,'server_type':quote.get('type'),'price_multiplier':str(price),
            'stake':format(value,'.2f'),'required_options':[name],'server_declared':True,
            'declared_additional_types':quote.get('additionalTypes') or [],
            'execution_blocker':'UNSUPPORTED_ADDITIONAL_TYPES' if unsupported_extra else 'UNKNOWN_SERVER_TYPE' if kind=='UNKNOWN_FEATURE' else None})
    if (init.get('currency') or {}).get('code')!='EUR':raise Unlearned('Nolimit City: escala monetaria no demostrada para esta moneda')
    complete=all(m['kind']!='UNKNOWN_FEATURE' for m in modes)
    source='init.game.featureBuyTimesBetValue/allowedFeatureBets/featureBetLevels'
    domains={category:{'complete':complete,'source':source,'options':[m.get('selector') for m in modes if m['kind']==kind]}
             for category,kind in [('purchase','PURCHASE'),('feature_spin','FEATURE_SPIN')]}
    # BOOSTED_BET proves its server category, not an antebet UI role.
    for mode in modes:
        catalog=(init.get('features') or {}).get('available',[])
        game_modes=init.get('allowedGameModes',[])
        if (isinstance(catalog,list) and all(isinstance(v,str) and v for v in catalog)
                and len(catalog)==len(set(catalog))):mode['declared_feature_catalog']=list(catalog)
        if isinstance(game_modes,list) and all(isinstance(v,str) for v in game_modes):mode['declared_game_modes']=list(game_modes)
        mode['declared_feature_options']=list(allowed)
        mode['declared_purchase_options']=[item['selector'] for item in modes if item['kind']=='PURCHASE']
        mode['declared_feature_categories']=[category for category,kind in [('BONUS_BUY','PURCHASE'),('BOOSTED_BET','FEATURE_SPIN')]
            if any(item['kind']==kind for item in modes)]
        if _row_response(game):mode['response_profile']='rows_freespin_and_collect/v1'
        mode['observation_contract']='independent-server-observations/v1'
        mode['wire_command']='normalBet' if mode['kind']=='SPIN' else 'featureBet'
        mode.update(executable=mode['kind']!='UNKNOWN_FEATURE' and not mode.get('execution_blocker'),validated=False,coverage_required=True,
                    covered_options=[],sample_counts={},evidence_level='SERVER_ADVERTISED',observed=False,
                    request_shape={'type':'normalBet','bet':mode['stake']} if mode['kind']=='SPIN' else
                        {'type':'featureBet','bet':mode['stake'],'featureName':mode['selector'],'playerInteraction':{'featureName':mode['selector']}})
    return modes,domains
