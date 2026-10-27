"""Server state observations independent of monetary response dialects.

Catalog recognition never grants permission to execute an unknown phase.
"""

def _labels(value):
    if not isinstance(value,list) or any(not isinstance(v,str) or not v for v in value) or len(value)!=len(set(value)):
        raise ValueError('Nolimit City: catálogo de estados inválido')
    return list(value)

def initial_state(init):
    game=init.get('game') or {};features=init.get('features') or {}
    if (init.get('init')!='ok' or game.get('isRestoreState') is not False
            or game.get('mode')!='NORMAL' or game.get('nextMode')!='NORMAL'
            or type(init.get('remainingFreeSpins')) is not int or init['remainingFreeSpins']!=0):
        raise ValueError('Nolimit City: sesión inicial no demuestra estado nuevo y normal')
    for key in ('freespinsLeft','respinsLeft','secondStageFsLeft','freespinsPlayed','freeSpinsPlayed','freespinPlayed','numberOfFreespinsPlayed'):
        if key in game and (type(game[key]) is not int or game[key]!=0):
            raise ValueError('Nolimit City: contador pendiente o desconocido: '+key)
    for key in ('wasFeatureBuy','freespinTriggeredThisSpin'):
        if key in game and game[key] is not False:raise ValueError('Nolimit City: función pendiente en inicialización')
    if not isinstance(features,dict) or features.get('active') not in (None,'','NORMAL'):
        raise ValueError('Nolimit City: fase activa en inicialización')
    catalog=_labels(features.get('available',[]))
    return {'state':'IDLE','catalog':catalog,'source':'confirmed_fresh_init_normal_and_no_pending_counters'}

KNOWN_PHASES={'FREESPIN','FREESPIN_BETTER','FREESPIN_SUPER','SUPER_FREESPIN',
    'RESPIN','FREESPIN_MINIGAME','FREESPIN_AVALANCHE','SUPER_FREESPIN_AVALANCHE',
    'NORMAL_AVALANCHE','AVALANCHE_NORMAL','AVALANCHE_FREESPIN','AVALANCHE_FREESPIN_SUPER',
    'NORMAL_AVALANCHE_RESPIN','FREESPIN_AVALANCHE_RESPIN','SUPER_FREESPIN_AVALANCHE_RESPIN',
    'STACKED_RESPIN_FREESPIN','FREESPIN_TRIGGER','COIN_SPIN','EXTRA_SPIN','GAMBLE','FREESPIN_PICK'}

def feature_observation(answer,catalog=(),game_modes=(),purchase_options=(),alternate_catalogs=()):
    game=answer.get('game') or {};features=answer.get('features')
    if not isinstance(features,dict):return {'kind':'UNRESOLVED_MENU','reason':'missing_features_object'}
    active=features.get('active');available=features.get('available')
    if isinstance(active,str) and not active.strip(' \t\r\n'):active=None
    if available is not None:
        try:values=_labels(available)
        except ValueError:return {'kind':'UNRESOLVED_MENU','reason':'invalid_available'}
        catalogs=[catalog,*alternate_catalogs]
        purchase_categories={'FREESPIN'} if purchase_options else set()
        if purchase_options and purchase_categories:catalogs.append(list(purchase_categories))
        matches=any(len(values)==len(items) and set(values)==set(items) for items in catalogs)
        if values and not matches:
            return {'kind':'UNRESOLVED_MENU','available':values,'source':'unmatched_runtime_domain'}
    else:values=[]
    if active not in (None,''):
        mode=game.get('mode');next_mode=game.get('nextMode')
        phase=(active in set(game_modes)|KNOWN_PHASES and active in (mode,next_mode)
            and (next_mode!='NORMAL' or mode!='NORMAL'))
        free_modes={'FREESPIN','FREESPIN_BETTER','FREESPIN_SUPER','SUPER_FREESPIN','FREESPIN_AVALANCHE','SUPER_FREESPIN_AVALANCHE'}
        left=game.get('freespinsLeft')
        free_category=((active in free_modes or active=='FREESPINS')
            and (active in purchase_options or active in catalog)
            and ((next_mode in free_modes and type(left) is int and left>=0)
                or (mode in free_modes and next_mode=='NORMAL' and type(left) is int and left==0)))
        respin_category=(active=='RESPIN' and next_mode in ('NORMAL_AVALANCHE_RESPIN','FREESPIN_AVALANCHE_RESPIN','SUPER_FREESPIN_AVALANCHE_RESPIN','NORMAL_AVALANCHE','FREESPIN_AVALANCHE','SUPER_FREESPIN_AVALANCHE'))
        stacked_category=(active=='STACKED_RESPIN_FS' and next_mode=='STACKED_RESPIN_FREESPIN')
        phase=phase or free_category or respin_category or stacked_category
        root=(active in purchase_options and game.get('wasFeatureBuy') is True
            and mode=='NORMAL' and next_mode!='NORMAL')
        if not phase and not root:return {'kind':'UNRESOLVED_PHASE','active':active}
        return {'kind':'PHASE','active':active,'available':values,'source':'init_game_modes_or_purchase_domain'}
    return {'kind':'CATALOG' if values else 'NONE','available':values,'source':'exact_initial_catalog' if values else 'no_advertised_menu'}


def settled_state(answer):
    """A confirmed normal state needs a zero remaining counter, not its spelling."""
    game=answer.get('game') or {};features=answer.get('features') or {}
    if (answer.get('feature_observation') or {}).get('kind') in ('UNRESOLVED_MENU','UNRESOLVED_PHASE'):return False
    if game.get('nextMode')!='NORMAL' or features.get('available')!=[] or features.get('active') not in (None,''):
        return False
    if 'pendingWin' in answer and answer['pendingWin'] is not False:return False
    if 'respinActive' in game and game['respinActive'] is not False:return False
    counters=[]
    if 'remainingFreeSpins' in answer:counters.append(answer['remainingFreeSpins'])
    for key in ('freespinsLeft','respinsLeft','secondStageFsLeft'):
        if key in game:counters.append(game[key])
    return bool(counters) and all(type(value) is int and value==0 for value in counters)


def settled_catalog_subset(answer,mode,*,completed_phase=None):
    """Terminal view; caller proves wallet and any non-normal phase completion."""
    game=answer.get('game') or {};features=answer.get('features') or {}
    if (answer.get('feature_observation') or {}).get('kind')!='UNRESOLVED_MENU':return None
    if game.get('nextMode')!='NORMAL':return None
    if game.get('mode')!='NORMAL' and (not isinstance(completed_phase,str) or game.get('mode')!=completed_phase):return None
    active=features.get('active')
    purchase_label=(mode.get('kind')=='PURCHASE' and active==mode.get('selector')
        and active in mode.get('declared_purchase_options',()) and game.get('wasFeatureBuy') is True)
    if active not in (None,'') and not purchase_label:return None
    try:values=_labels(features.get('available'))
    except ValueError:return None
    purchases=mode.get('declared_purchase_options',())
    if not mode.get('server_declared') or not values or not set(values)<=set(purchases):return None
    for node in (answer,game):
        if any(node.get(key) not in (None,False,[],{}) for key in ('screens','pickAndClick','gambleOptions','gambleCollect')):return None
    candidate={**answer,'features':{**features,'available':[],'active':''},
        'feature_observation':{'kind':'SETTLED_CATALOG_SUBSET','available':values,
            'source':'declared_purchase_subset_normal_counters_and_reconciled_wallet'}}
    return candidate if settled_state(candidate) else None
