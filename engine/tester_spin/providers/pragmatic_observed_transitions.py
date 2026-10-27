"""Bounded transition families demonstrated by official-client demo HARs.

Evidence: 2026-10-02T23-06-58-694Z (vswayslions automatic FS respin),
2026-10-02T23-10-29-934Z (vs20wildparty bg_0 choice, doBonus ind=1).
Unknown signatures retain the existing contract validation and review path.
"""
import hashlib
import re
import json
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def game_rules():
    rules=json.loads(Path(__file__).with_name('pragmatic_game_rules.json').read_text(encoding='utf-8'))
    if rules.get('schema')!='pragmatic/observed-game-rules/v1':raise ValueError('Unsupported game rule schema')
    return rules


def observed_spin_fields(symbol):
    # Official client Olympus selection, HAR 2026-10-03T01-33-18-693Z.
    # l=15 is the wire line count; doInit l=10 remains the stake scale.
    rules=game_rules()
    entry=rules['games'].get(symbol)
    if not entry:return {}
    profile=rules['profiles'][entry['profile']]
    if profile['kind']!='spin_fields':return {}
    fields=profile['fields']
    if not profile.get('evidence') or set(fields)-{'l','ind','prg_i'} or any(not re.fullmatch(r'0|[1-9][0-9]{0,3}',v) for v in fields.values()):
        raise ValueError('Invalid observed spin rule')
    return dict(fields)


def game_profile(symbol):
    rules=game_rules();entry=rules['games'].get(symbol)
    return rules['profiles'][entry['profile']] if entry else {}


def apply_spin_rule(fields,symbol):
    profile=game_profile(symbol)
    if profile.get('kind')=='scratchcard':
        if fields.get('action')=='doSpin':fields.update(profile['fields'])
        else:fields.pop('tickets',None)
    else:fields.update(observed_spin_fields(symbol))
    for key in profile.get('omit_fields',[]):fields.pop(key,None)
    if 'pur' in fields and profile.get('purchase_s_info') in {'n','t'}:
        fields['sInfo']=profile['purchase_s_info']


def observed_next_action(response,symbol):
    rule=game_profile(symbol).get('terminal')
    if rule and response.get(rule['key'])==rule['value'] and not any(response.get(k) for k in ('fs','fsmax','rs','rs_c')):
        if game_profile(symbol).get('kind')!='scratchcard' or all(response.get(k,'0')=='0' for k in ('t_left','fs_left')):return 's'
    if response.get('na'):return str(response['na'])
    return ''


def observed_continuation(response,symbol):
    if mystery_selection(response, symbol) is not None:
        return 'doMysteryScatter'
    return game_profile(symbol).get('continuations',{}).get(response.get('na'))


def observed_bonus_rule(response, symbol, override=None):
    if symbol == 'vs1600drago':
        expected = {'na':'b','bgid':'0','bgt':'45','end':'0','rsb_m':'3','rsb_w_mask':'wd,ms,fs,m'}
        if (any(response.get(k) != v for k,v in expected.items())
                or not re.fullmatch(r'0|1|2', str(response.get('rsb_c','')))
                or not re.fullmatch(r'0|[1-9][0-9]{0,3}', str(response.get('rsb_p','')))
                or not re.fullmatch(r'[0-9]+(?:,[0-9]+){3}', str(response.get('rsb_w','')))):
            return None
        if override is not None:
            raise ValueError('Automatic Drago bonus has no player selector')
        evidence = 'Official HAR vs1600drago 2026-10-09T00-08-07-813Z: nine doBonus requests without ind; bgt=45 -> free spins'
        return {'fields':{}, 'domain':[], 'selected':None, 'default':None,
                'branch_signature':'PRAGMATIC:observed-auto:vs1600drago:bgt=45',
                'domain_basis':'Automatic continuation, no selectable player menu',
                'contract_source':evidence, 'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
                'selection_policy':'observed_automatic_continuation'}
    if symbol == 'vswaysbbhas':
        group = _bonus_group(response)
        if group is None:
            return None
        family, state = group
        if (family != 'bg' or set(state) != {'bgid','bgt','end','level','lifes','rw'}
                or any(state.get(k) != v for k,v in {'bgid':'0','bgt':'69','end':'0'}.items())
                or (state['level'],state['lifes']) not in {('0','3'),('1','2'),('2','1')}
                or not re.fullmatch(r'[0-9]+\.[0-9]{2}', state['rw'])):
            return None
        if override is not None and str(override) != '0':
            raise ValueError('Observed hold-spinner continuation requires ind=0')
        evidence = 'Official demo HAR vswaysbbhas 2026-10-06 04-33-41: purchase pur=1, eight doBonus(ind=0), na=cb then doCollectBonus -> na=s'
        return {'fields':{'ind':'0'}, 'domain':['0'], 'selected':'0', 'default':None,
                'branch_signature':'PRAGMATIC:observed-continuation:vswaysbbhas:bgt=69:ind=0',
                'domain_basis':'Official client continuation; no selectable menu is advertised',
                'contract_source':evidence, 'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
                'selection_policy':'observed_continuation'}
    profile = game_profile(symbol)
    if profile.get('kind') != 'bonus_fields':
        return None
    if any(response.get(key) not in values for key, values in profile['match'].items()):
        return None
    fields = profile['fields']
    if set(fields) != {'ind'} or not re.fullmatch(r'0|[1-9][0-9]{0,3}', fields['ind']) or not profile.get('evidence'):
        raise ValueError('Invalid observed bonus rule')
    selected = fields['ind']
    if override is not None and str(override) != selected:
        raise ValueError('Observed continuation has no alternative selector')
    evidence = profile['evidence']
    return {'fields':dict(fields), 'domain':[selected], 'selected':selected, 'default':None,
            'branch_signature':f'PRAGMATIC:observed-continuation:{symbol}:bgt={response["bgt"]}:ind={selected}',
            'domain_basis':'Observed continuation selector, not an inferred menu choice domain',
            'contract_source':evidence, 'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
            'selection_policy':'observed_continuation'}


def _three_respin_screens(raw):
    if not isinstance(raw,str) or len(raw)>12000:return False
    groups=re.findall(r'([A-Za-z_][A-Za-z_0-9]*):\{([^{}]*)\}',raw)
    if (not 2<=len(groups)<=14 or raw!='{'+','.join(name+':{'+body+'}' for name,body in groups)+'}'
            or [name for name,_ in groups[:2]]!=['reg','top']
            or len({name for name,_ in groups})!=len(groups)):return False
    for _,body in groups[2:]:
        fields=re.findall(r'([A-Za-z_][A-Za-z_0-9]*):"([^"\\]*)"',body)
        if (body!=','.join(k+':"'+v+'"' for k,v in fields)
                or len(fields)!=4 or {k for k,_ in fields}!={'mo_c','mo_tv','mo_tw','mo_wpos'}):return False
        values=dict(fields)
        if not re.fullmatch(r'[1-9][0-9]{0,3}',values['mo_c']):return False
        if not re.fullmatch(r'[0-9]{1,12}',values['mo_tv']):return False
        if not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,4})?',values['mo_tw']):return False
        if not re.fullmatch(r'[0-9]{1,4}(?:,[0-9]{1,4}){0,127}',values['mo_wpos']):return False
        positions=values['mo_wpos'].split(',')
        if len(set(map(int,positions)))!=len(positions):return False
    return True


def automatic_fs_respin(response, symbol=""):
    bank_auto = _empty_bank_auto(response, symbol)
    three_respins = response.get('rs_m')=='3' and _three_respin_screens(response.get('g'))
    dynamic_cascade = (response.get('rs_more')=='1'
        and all(re.fullmatch(r'0|[1-9][0-9]{0,3}',str(response.get(k,''))) for k in ('rs_m','rs_c','rs_p'))
        and int(response['rs_m'])==int(response['rs_c'])==int(response['rs_p'])+1)
    if (response.get('na') != 's' or response.get('rs') != 'mc'
            or 'rs_t' in response or not re.fullmatch(r'0|[1-9][0-9]*', str(response.get('rs_p','')))
            or (response.get('rs_m') != '1' and not three_respins and not dynamic_cascade and not bank_auto)
            or any('sr~' in str(value) for value in response.values())):
        return False
    profile=game_profile(symbol) if symbol else {}
    signatures=profile.get('automatic_respin')
    if isinstance(signatures,dict):signatures=[signatures]
    observed=(isinstance(signatures,list) and 1<=len(signatures)<=2 and bool(profile.get('evidence'))
        and all(item in ({'rs_m':'1','rs_c':'1','rs_p':'0'},{'rs_m':'1','rs_c':'1','rs_p':'1'}) for item in signatures)
        and any(all(response.get(k)==v for k,v in item.items()) for item in signatures))
    observed = observed or bank_auto
    if ('tmb_win' in response or not observed) and not re.fullmatch(r'(?:[0-9]+|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]+)?',str(response.get('tmb_win',''))): return False
    if not re.fullmatch(r'[1-9][0-9]*',str(response.get('rs_c',''))): return False
    if 'fs' not in response and 'fsmax' not in response: return True
    values = [str(response.get(key, '')) for key in ('fs','fsmax')]
    return all(re.fullmatch(r'[1-9][0-9]*', v) for v in values) and int(values[0]) <= int(values[1])


def _bonus_group(response):
    raw = str(response.get('g', ''))
    if response.get('na') != 'b' or len(raw) > 4096:
        return None
    match = re.fullmatch(r'\s*\{([A-Za-z_][A-Za-z_0-9]*):\{([^{}]*)\}\}\s*', raw)
    if not match:
        pieces=re.findall(r'([A-Za-z_][A-Za-z_0-9]*):\{([^{}]*)\}',raw)
        if not pieces or raw!='{'+','.join(name+':{'+body+'}' for name,body in pieces)+'}':return None
        groups=[_bonus_group({'na':'b','g':'{'+name+':{'+body+'}}'}) for name,body in pieces]
        if any(group is None for group in groups):return None
        bonuses=[group for group in groups if 'bgt' in group[1] and group[1].get('end')=='0']
        if len(bonuses)!=1:return None
        if any(group[1].get('end') not in {'0','1'} for group in groups if 'bgt' in group[1]):return None
        screens=[group[1] for group in groups if 'bgt' not in group[1]]
        screen_keys={'s','sa','sb','sh','st','sw'}
        for screen in screens:
            if screen_keys<=set(screen)<=screen_keys|{'reel_set','mo','mo_t'} and screen['st']=='rect':continue
            if set(screen)<={'mo','mo_t'}:continue
            # Reward overlays accompany a menu but contribute no action domain.
            if (set(screen)=={'mo_tv','mo_tw','mo_wpos'}
                    and all(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',screen[k]) for k in ('mo_tv','mo_tw'))
                    and re.fullmatch(r'[0-9]+(?:,[0-9]+)*',screen['mo_wpos'])):continue
            return None
        return bonuses[0]
    family=match[1]
    chunks = match[2].split('",')
    pairs=[]
    for index, chunk in enumerate(chunks):
        if index < len(chunks)-1: chunk += '"'
        item=re.fullmatch(r'\s*([a-z_][a-z_0-9]*):"([^"\\]*)"\s*',chunk)
        if not item: return None
        pairs.append(item.groups())
    fields=dict(pairs)
    if len(fields)!=len(pairs):return None
    return family,fields


def bonus_choice(response, override=None):
    group=_bonus_group(response)
    if group is None:return None
    family,fields=group
    if ';' in fields.get('ch_k',''):
        return _segmented_bonus_choice(family, fields, override)
    expected={'ask','bgid','bgt','ch_k','ch_v','end','rw'}
    optional={'level','lifes','rw_c','trail','ch_h','reel_set','s','sa','sb','sh','st','sw','mo','mo_t'}
    if not expected<=set(fields) or set(fields)-expected-optional:
        return None
    if any(fields[key] != value for key,value in {'ask':'0','bgt':'69','end':'0'}.items()) or not re.fullmatch(r'0|[1-9][0-9]{0,3}',fields['bgid']):
        return None
    if not re.fullmatch(r'0(?:\.0+)?',fields['rw']): return None
    values=fields['ch_v'].split(',');labels=fields['ch_k'].split(',')
    if (not 1 <= len(values) <= 128 or len(values) != len(labels)
            or any(not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',v) for v in values)
            or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z_0-9-]{0,63}',v) for v in labels)):
        return None
    if 'ch_h' in fields:
        history=fields['ch_h'].split(',')
        if any(not re.fullmatch(r'0~(?:0|[1-9][0-9]{0,3})',v) or int(v[2:])>=len(labels) for v in history):return None
    if family=='f':
        if fields.get('level')!='0' or fields.get('lifes')!='1' or any(not re.fullmatch(r'fm|f[1-9][0-9]*',v) for v in labels):return None
        domain=list(map(str,range(len(labels))))
        evidence='HAR:vsways5lionsr:f:bgt=69:option-index->doBonus(ind):2026-10-02T23-40-19-976Z'
        basis='Official demo client sends the zero-based option index; ch_v contains reward values'
    else:
        if any(k in fields and not re.fullmatch(r'0|[1-9][0-9]*',fields[k]) for k in ('level','lifes','rw_c')):return None
        domain=list(map(str,range(len(labels))))
        evidence='HAR:vswaysdh1000:2026-10-03T01-25-11-735Z+network-event;vs20mammoth:bg_1:2026-10-03T02-18-28-001Z+network-event:option-index->doBonus(ind)'
        basis='Official client sends the option position; ch_v describes rewards (Dog House values 7,7 map to indices 0,1)'
    selected=domain[0] if override is None else str(override)
    if selected not in domain: raise ValueError('Bonus choice is outside the server domain')
    return {'fields':{'ind':selected},'domain':domain,'selected':selected,'default':None,
            'branch_signature':'PRAGMATIC:bonus-choice:bgt=69:choices='+','.join(domain)+':family='+family+':labels='+','.join(labels),
            'domain_basis':basis,
            'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
            'selection_policy':'first_available_test_choice' if override is None else 'explicit_override'}


def _segmented_bonus_choice(family, fields, override):
    # Official Kraken 2 HAR: ask selects a menu, ind selects within that menu.
    required={'ask','bgid','bgt','ch_k','ch_v','end','rw'}
    optional={'level','lifes','trail','rw_c','ch_h','status','wins','wins_mask','wi'}
    if not required<=set(fields) or set(fields)-required-optional:
        return None
    if any(fields[k]!=v for k,v in {'bgt':'69','end':'0','rw':'0.00'}.items()):return None
    if any(not re.fullmatch(r'0|[1-9][0-9]*',fields[k]) for k in ('bgid','ask')):return None
    if any(k in fields and not re.fullmatch(r'0|[1-9][0-9]*',fields[k]) for k in ('level','lifes','rw_c')):return None
    labels=[row.split(',') for row in fields['ch_k'].split(';')]
    values=[row.split(',') for row in fields['ch_v'].split(';')]
    if not 2<=len(labels)<=16 or len(labels)!=len(values):return None
    for row,numbers in zip(labels,values):
        if not 1<=len(row)<=128 or len(row)!=len(numbers):return None
        if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z_0-9-]{0,63}',v) for v in row):return None
        if any(not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',v) for v in numbers):return None
    if int(fields['ask'])>=len(labels):return None
    ask=int(fields['ask']);domain=list(map(str,range(len(labels[ask]))))
    if 'ch_h' in fields:
        for pair in fields['ch_h'].split(','):
            match=re.fullmatch(r'([0-9]+)~([0-9]+)',pair)
            if not match or int(match[1])>=len(labels) or int(match[2])>=len(labels[int(match[1])]):return None
    if all(v.isdecimal() for v in labels[ask]):
        # Numeric hidden menus are currently evidenced only for this exact table.
        if (family!='bg_0' or ask!=2 or labels != [['fs','deal_or_not'],['deal','not_deal'],list(map(str,range(16))),['swap','not_swap']]
                or values != [['0','1'],['0','1'],['0']*16,['0','1']]):return None
        status=fields.get('status','').split(',')
        if len(status)!=16 or any(v not in {'0','1'} for v in status):return None
        domain=[str(i) for i,v in enumerate(status) if v=='0']
    if not domain:return None
    selected=domain[0] if override is None else str(override)
    if selected not in domain:raise ValueError('Bonus choice is outside the active menu domain')
    evidence='HAR:vs20kraken2:2026-10-03T02-42-33-219Z+HTTP-tab31:ask-table->doBonus(ind), no ask request field'
    return {'fields':{'ind':selected},'domain':domain,'selected':selected,'default':None,
            'branch_signature':f'PRAGMATIC:bonus-choice:bgt=69:family={family}:ask={ask}:labels='+','.join(labels[ask]),
            'domain_basis':'Official menu table indexed by ask; positions within active table, hidden cells exclude positive status',
            'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
            'selection_policy':'first_available_test_choice' if override is None else 'explicit_override'}


def _range_bonus_pick(family, fields, override):
    # Bubble Up official HAR: ch_v encodes an inclusive position range.
    required={'ask','bgid','bgt','ch_k','ch_v','end','level','lifes','rw','rw_c','status','wins','wins_mask'}
    if family!='b' or not required<=set(fields) or set(fields)-required-{'ch_h','wi'}:return None
    if any(fields[k]!=v for k,v in {'ask':'0','bgid':'0','bgt':'69','ch_k':'pck','end':'0','rw_c':'0'}.items()):return None
    if not re.fullmatch(r'0(?:\.0+)?',fields['rw']):return None
    bounds=re.fullmatch(r'0:([0-9]+)',fields['ch_v'])
    if not bounds or not 1<=int(bounds[1])+1<=128:return None
    size=int(bounds[1])+1
    if not re.fullmatch(r'[1-9][0-9]{0,2}',fields['lifes']) or int(fields['lifes'])>size:return None
    status=fields['status'].split(',');wins=fields['wins'].split(',');masks=fields['wins_mask'].split(',')
    if any(len(row)!=size for row in (status,wins,masks)):return None
    if any(not re.fullmatch(r'0|[1-9][0-9]{0,2}',v) for v in status+[fields['level']]):return None
    if any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',v) for v in wins):return None
    if any(not re.fullmatch(r'[A-Za-z0-9_]{1,16}',v) for v in masks):return None
    numbers=list(map(int,status));level=int(fields['level'])
    if level>=size or sorted(v for v in numbers if v)!=list(range(1,level+1)):return None
    if any((n==0)!=(mask=='h') for n,mask in zip(numbers,masks)):return None
    if level:
        history=fields.get('ch_h','').split(',')
        if len(history)!=level or any(not re.fullmatch(r'0~[0-9]+',v) for v in history):return None
        picked=[int(v[2:]) for v in history]
        if len(set(picked))!=level or any(i>=size or numbers[i]!=n+1 for n,i in enumerate(picked)):return None
        if fields.get('wi')!=str(picked[-1]):return None
    elif 'ch_h' in fields or 'wi' in fields:return None
    domain=[str(i) for i,n in enumerate(numbers) if n==0]
    if not domain:return None
    selected=domain[0] if override is None else str(override)
    if selected not in domain:raise ValueError('Bonus position is already revealed or outside the range')
    evidence='HAR:vs20bblup:2026-10-08T23-52-20-138Z+23-52-59-869Z:pck range/status->doBonus(ind)'
    return {'fields':{'ind':selected},'domain':domain,'selected':selected,'default':None,
        'branch_signature':f'PRAGMATIC:range-pick:bgt=69:level={level}:status='+','.join(status),
        'coverage_branch_signature':f'PRAGMATIC:bonus-pick:bgt=69:size={size}:level={level}',
        'coverage_policy':'hidden-position-structural/v1','pick_level':level,'pick_size':size,
        'pick_history':fields.get('ch_h','').split(',') if fields.get('ch_h') else [],
        'pick_status':status,'pick_masks':masks,'pick_wins':wins,
        'domain_basis':'Official client selects a zero-based hidden position in ch_v inclusive range',
        'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
        'selection_policy':'first_available_test_choice' if override is None else 'explicit_override'}


def progressive_hidden_pick(response, override=None):
    """Flat, single-pick progressive grid witnessed in the official demo HAR.

    Persistent progress alone never authorizes a bonus action. Only a full,
    unrevealed menu at its threshold does; unknown shapes remain pending.
    """
    if response.get('na') != 'b' or any(key in response for key in ('g','bgt','bgid','ch_k','ch_v')):
        return None
    if any(response.get(k) != v for k,v in {
        'prg_m':'cp,tp,r,acw', 'level':'0', 'lifes':'1', 'bw':'1', 'end':'0'
    }.items()):
        return None
    progress = str(response.get('prg','')).split(',')
    if len(progress) != 4 or any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',v) for v in progress):
        return None
    if not progress[0].isdigit() or not progress[1].isdigit() or int(progress[0]) != int(progress[1]) or int(progress[1]) < 1 or progress[2] != '0':
        return None
    from decimal import Decimal
    reward = str(response.get('rw',''))
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',reward) or Decimal(reward) != Decimal(progress[3]):
        return None
    statuses = str(response.get('status','')).split(',')
    wins = str(response.get('wins','')).split(',')
    masks = str(response.get('wins_mask','')).split(',')
    size = len(statuses)
    if not 1 <= size <= 128 or len(wins) != size or len(masks) != size:
        return None
    if any(v != '0' for v in statuses) or any(v != 'h' for v in masks) or any(not re.fullmatch(r'0(?:\.0+)?',v) for v in wins):
        return None
    domain = list(map(str,range(size)))
    selected = domain[0] if override is None else str(override)
    if selected not in domain:
        raise ValueError('Progressive bonus position is outside the hidden grid')
    evidence = 'HAR:2026-10-09T10-39-55-686Z:flat-progressive-grid;client BonusPickConnection.SendItemPick(itemId)->VsBonusGamePlayerChoice.Index->doBonus(ind);observed ind=7,4 -> end=1 -> doCollectBonus'
    return {'fields':{'ind':selected}, 'domain':domain, 'selected':selected, 'default':None,
        'branch_signature':f'PRAGMATIC:progressive-grid:flat:size={size}:level=0',
        'coverage_branch_signature':f'PRAGMATIC:progressive-grid:flat:size={size}:level=0',
        'coverage_policy':'hidden-position-structural/v1',
        'domain_basis':'Official client indexes the hidden status/wins grid; one pick reveals rewards and ends the bonus',
        'contract_source':evidence, 'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
        'selection_policy':'first_available_test_choice' if override is None else 'explicit_override'}


def parameterized_gamble_selection(response, override=None):
    """Certify parameterized play/sm/sp menus, not a game-name exception."""
    group = _bonus_group(response)
    if group is None or group[0] != 'gambling':return None
    fields = group[1]
    required = {'ask','bgid','bgt','ch_k','ch_v','end','level','lifes','rw'}
    if not required <= set(fields) or set(fields)-required-{'ch_h'}:return None
    if any(fields[k]!=v for k,v in {'bgid':'0','bgt':'69','end':'0','lifes':'1'}.items()):return None
    if not re.fullmatch(r'0(?:\.0+)?',fields['rw']):return None
    if not fields['ask'].isdigit() or fields['level']!=fields['ask']:return None
    labels = [row.split(',') for row in fields['ch_k'].split(';')]
    values = [row.split(',') for row in fields['ch_v'].split(';')]
    ask = int(fields['ask'])
    if not 1<=len(labels)<=128 or len(values)!=len(labels) or ask!=len(labels)-1:return None
    maps = []
    for row,numbers in zip(labels,values):
        if not 2<=len(row)<=3 or row[0]!='play' or len(numbers)!=len(row):return None
        roles = {'0':'0'}; contexts=[]
        for index,label in enumerate(row[1:],1):
            match=re.fullmatch(r'(sm|sp)([1-9][0-9]{0,3})s([1-9][0-9]{0,3})-([0-9]{1,4})',label)
            if not match:return None
            kind,a,b,c=match.groups();a,b,c=map(int,(a,b,c))
            if kind=='sm':
                if c!=b-1:return None
                contexts.append((a,b));role='1'
            else:
                if c!=b+1:return None
                contexts.append((b,a));role='2'
            if role in roles.values():return None
            roles[str(index)]=role
        if len(set(contexts))!=1 or numbers!=list(roles.values()):return None
        maps.append(roles)
    history = fields.get('ch_h','').split(',') if fields.get('ch_h') else []
    if len(history)!=ask:return None
    for index,pair in enumerate(history):
        if not re.fullmatch(str(index)+r'~[0-2]',pair) or pair.split('~')[1] not in maps[index]:return None
    domain=list(maps[ask]);selected=domain[0] if override is None else str(override)
    if selected not in domain:raise ValueError('Gamble choice is outside the active menu')
    evidence='HAR:2026-10-09T00-15-45-564Z:gambling play/sm/sp parameterized menus;client GamblingBOM.UpdateItems maskIndices.indexOf(i)->GamblingItemBOM.button.index->doBonus(ind);ch_v maps history index to semantic action, not wire ind;history is not a new control'
    return {'fields':{'ind':selected},'domain':domain,'selected':selected,'default':None,
        'branch_signature':'PRAGMATIC:parameterized-gamble:bgt=69:play-sm-sp',
        'coverage_branch_signature':'PRAGMATIC:parameterized-gamble:bgt=69:play-sm-sp',
        'coverage_policy':'parameterized-menu-actions/v1','coverage_domain_map':maps[ask],
        'coverage_class_labels':{'0':'play','1':'sm','2':'sp'},
        'menu_ask':ask,'menu_history':history,'menu_keys':fields['ch_k'],'menu_values':fields['ch_v'],
        'domain_basis':'Active menu positions; sm/sp numeric parameters and prior menu history do not create controls',
        'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
        'selection_policy':'first_available_test_choice' if override is None else 'explicit_override'}


def parameterized_gamble_acknowledged(record,response):
    group=_bonus_group({**response,'na':'b'})
    if group is None or group[0]!='gambling':return False
    fields=group[1];ask=record.get('menu_ask');selected=str(record.get('selected'))
    if fields.get('bgid')!='0' or fields.get('bgt')!='69' or not re.fullmatch(r'0(?:\.0+)?',fields.get('rw','')):return False
    expected=list(record.get('menu_history',[]))+[f'{ask}~{selected}']
    if fields.get('ch_h','').split(',')!=expected or fields.get('level')!=str(ask+1):return False
    if fields.get('end')=='0':
        valid = parameterized_gamble_selection(response)
        return (valid is not None and fields.get('ch_k','').startswith(record.get('menu_keys','')+';')
            and fields.get('ch_v','').startswith(record.get('menu_values','')+';'))
    if fields.get('end')=='1':
        return (response.get('na') in {'s','c'} and fields.get('lifes') in {'0','1'}
            and fields.get('ch_k')==record.get('menu_keys') and fields.get('ch_v')==record.get('menu_values'))
    return False


def repeatable_yes_no_selection(response, override=None):
    group=_bonus_group(response)
    if group is None or group[0]!='bg':return None
    fields=group[1]
    required={'ask','bgid','bgt','ch_k','ch_v','end','rw','rw_c'}
    if not required<=set(fields) or set(fields)-required-{'ch_h'}:return None
    if any(fields[k]!=v for k,v in {'bgid':'0','bgt':'69','end':'0','rw_c':'0'}.items()):return None
    if not re.fullmatch(r'0(?:\.0+)?',fields['rw']) or not re.fullmatch(r'0|[1-9][0-9]{0,2}',fields['ask']):return None
    ask=int(fields['ask']);labels=fields['ch_k'].split(';');values=fields['ch_v'].split(';')
    if not 1<=len(labels)<=128 or len(labels)!=ask+1 or len(values)!=len(labels):return None
    if any(row!='y,n' for row in labels):return None
    if any(not re.fullmatch(r'[1-9][0-9]{0,15},[1-9][0-9]{0,15}',row) for row in values):return None
    history=fields.get('ch_h','').split(',') if fields.get('ch_h') else []
    if len(history)!=ask or any(not re.fullmatch(str(i)+r'~[01]',v) for i,v in enumerate(history)):return None
    selected='0' if override is None else str(override)
    if selected not in {'0','1'}:raise ValueError('Yes/no selection is outside the active menu')
    evidence='HAR:2026-10-09T19-00-12-597Z:bg y,n->doBonus(ind=0,1);repeated ask/history menus;ch_v values are not request indices'
    return {'fields':{'ind':selected},'domain':['0','1'],'selected':selected,'default':None,
        'branch_signature':'PRAGMATIC:repeatable-menu:bgt=69:family=bg:labels=y,n',
        'coverage_branch_signature':'PRAGMATIC:repeatable-menu:bgt=69:family=bg:labels=y,n',
        'coverage_policy':'repeatable-menu-actions/v1','menu_ask':ask,'menu_history':history,
        'menu_keys':fields['ch_k'],'menu_values':fields['ch_v'],
        'domain_basis':'Same yes/no controls at each depth; server ch_h acknowledges their positions',
        'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
        'selection_policy':'first_available_test_choice' if override is None else 'explicit_override'}


def repeatable_yes_no_acknowledged(record,response):
    group=_bonus_group({**response,'na':'b'})
    if group is None:
        # Terminal menus may retain a reel overlay. Validate that overlay with
        # the existing group parser, then retain the original terminal flag.
        raw=str(response.get('g',''))
        matches=list(re.finditer(r'bg:\{[^{}]*\bend:"1"[^{}]*\}',raw))
        if len(matches)==1:
            chunk=matches[0].group(0)
            active=chunk.replace('end:"1"','end:"0"',1)
            checked=_bonus_group({'na':'b','g':raw[:matches[0].start()]+active+raw[matches[0].end():]})
            if checked is not None and checked[0]=='bg':
                group=_bonus_group({'na':'b','g':'{'+chunk+'}'})
    if group is None or group[0]!='bg':return False
    f=group[1];ask=record['menu_ask'];selected=str(record['selected'])
    if f.get('bgid')!='0' or f.get('bgt')!='69' or not re.fullmatch(r'0(?:\.0+)?',f.get('rw','')):return False
    if f.get('ch_h','').split(',')!=record['menu_history']+[f'{ask}~{selected}']:return False
    if f.get('end')=='0':
        return (repeatable_yes_no_selection(response) is not None
            and f.get('ch_k','').startswith(record['menu_keys']+';')
            and f.get('ch_v','').startswith(record['menu_values']+';'))
    return (f.get('end')=='1' and f.get('rw_c')=='1' and response.get('na') in {'s','c'}
        and f.get('ch_k')==record['menu_keys'] and f.get('ch_v')==record['menu_values'])


def counter_bonus_continuation(response,override=None):
    group=_bonus_group(response)
    if group is None or group[0]!='bg':return None
    f=group[1]
    if set(f)!={'bgid','bgt','end','level','lifes','rw'}:return None
    if any(f[k]!=v for k,v in {'bgid':'0','bgt':'69','end':'0'}.items()):return None
    if f['level'] not in {'0','1','2'} or f['lifes'] not in {'1','2','3'} or int(f['level'])+int(f['lifes'])!=3:return None
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',f['rw']):return None
    if override is not None and str(override)!='0':raise ValueError('Counter bonus has only the observed continuation ind=0')
    evidence='HAR:2026-10-09T19-10-05-346Z:bg bgt69 level+lifes=3 -> doBonus(ind=0);reward resets counter;end1 -> doCollectBonus'
    return {'fields':{'ind':'0'},'domain':['0'],'selected':'0','default':None,
        'branch_signature':'PRAGMATIC:bonus-continuation:bg:bgt=69:counter-total=3',
        'domain_basis':'Observed single continuation; lives and reward are state, not separate choices',
        'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
        'selection_policy':'observed_continuation'}


def range_pick_acknowledged(record,response):
    group=_bonus_group({**response,'na':'b'})
    if group is None or group[0]!='b':return False
    f=group[1];selected=str(record['selected']);level=record['pick_level'];size=record['pick_size']
    statuses=f.get('status','').split(',');masks=f.get('wins_mask','').split(',');wins=f.get('wins','').split(',')
    if selected not in record['domain'] or any(len(row)!=size for row in (statuses,masks,wins)):return False
    expected=list(record['pick_status']);expected[int(selected)]=str(level+1)
    if statuses!=expected:return False
    if any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',value) for value in wins):return False
    for i in range(size):
        if str(i)==selected:
            if masks[i]=='h' or not re.fullmatch(r'[A-Za-z0-9_]{1,16}',masks[i]):return False
        elif masks[i]!=record['pick_masks'][i] or wins[i]!=record['pick_wins'][i]:return False
    if not (f.get('bgid')=='0' and f.get('bgt')=='69' and f.get('wi')==selected
        and f.get('ch_k')=='pck' and f.get('ch_v')==f'0:{size-1}'
        and f.get('level')==str(level+1)
        and f.get('ch_h','').split(',')==record['pick_history']+[f'0~{selected}']):return False
    if f.get('end')=='0':
        return response.get('na')=='b' and _range_bonus_pick('b',f,None) is not None
    required={'bgid','bgt','ch_k','ch_v','end','level','lifes','rw','rw_c','status','wins','wins_mask','ch_h','wi'}
    return (set(f)==required and f.get('end')=='1' and f.get('lifes')=='0'
        and f.get('rw_c')=='1' and re.fullmatch(r'0(?:\.0+)?',f.get('rw','')) is not None
        and response.get('na') in {'s','c','cb'})


def bonus_transition(response, override=None):
    repeated=repeatable_yes_no_selection(response,override=override)
    if repeated is not None:return repeated
    counter=counter_bonus_continuation(response,override=override)
    if counter is not None:return counter
    gamble = parameterized_gamble_selection(response, override=override)
    if gamble is not None:return gamble
    progressive = progressive_hidden_pick(response, override=override)
    if progressive is not None:return progressive
    choice=bonus_choice(response,override=override)
    if choice is not None:return choice
    group=_bonus_group(response)
    if group is None:return None
    family,fields=group
    range_pick=_range_bonus_pick(family,fields,override)
    if range_pick is not None:return range_pick
    wheel_keys={'bgid','bgt','end','rw','whms','whnwi','whsc','whvs','whws'}
    if wheel_keys<=set(fields) and not set(fields)-wheel_keys-{'rw_c','level','lifes','whs'}:
        if fields['bgt']!='69' or fields['end']!='0':return None
        if not all(re.fullmatch(r'0|[1-9][0-9]*',fields[k]) for k in ('bgid','whsc')):return None
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',fields['rw']):return None
        masks=[row.split(',') for row in fields['whms'].split(';')]
        values=[row.split(',') for row in fields['whvs'].split(';')]
        weights=[row.split(',') for row in fields['whws'].split(';')]
        if not 1<=len(masks)<=16 or len(values)!=len(masks) or len(weights)!=len(masks):return None
        for labels,numbers,chances in zip(masks,values,weights):
            if not 1<=len(labels)<=128 or len(numbers)!=len(labels) or len(chances)!=len(labels):return None
            if any(not re.fullmatch(r'[a-z0-9][a-z_0-9]{0,31}',v) for v in labels):return None
            if any(not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',v) for v in numbers):return None
            if any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',v) for v in chances):return None
        active=fields['whnwi'].split(',')
        if any(not re.fullmatch(r'0|[1-9][0-9]*',v) or int(v)>=len(masks) for v in active):return None
        if override is not None:raise ValueError('Automatic wheel has no selectable index')
        evidence='HAR:vs20bison:wheel:bgt=69->doBonus(no-ind):2026-10-03T01-20-13-076Z'
        return {'fields':{},'domain':[],'selected':None,'default':None,
            'branch_signature':f'PRAGMATIC:automatic-wheel:{family}:bgt=69',
            'domain_basis':'Server supplies wheel outcomes; official client requests the next wheel without ind',
            'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
            'selection_policy':'observed_automatic_continuation'}
    # Official Mission Fishin HAR: a completed bg_0 menu activates bg_1.
    if family=='bg_1' and fields=={'bgid':'1','bgt':'69','end':'0','rw':'0.00'}:
        if override is not None and str(override)!='0':raise ValueError('Observed continuation requires ind=0')
        evidence='HAR:vs10bbfmission:2026-10-08T23-49-09-382Z+23-50-12-663Z:bg_1->doBonus(ind=0)'
        return {'fields':{'ind':'0'},'domain':['0'],'selected':'0','default':None,
            'branch_signature':'PRAGMATIC:bonus-continuation:bg_1:bgt=69:minimal',
            'domain_basis':'Official demo continues the second bonus with ind=0',
            'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
            'selection_policy':'observed_continuation'}
    minimal={'bgid':'0','bgt':'69','end':'0','rw':'0.00'}
    if family in {'bg_0','bg','pc','pl','flat'} and fields in (minimal,{**minimal,'rw_c':'0'}):
        if override is not None and str(override)!='0':raise ValueError('Observed continuation requires ind=0')
        evidence='HAR:vs10bbsplxmas:bg_0:minimal->doBonus(ind=0):2026-10-03T00-43-39-528Z'
        if 'rw_c' in fields:
            evidence='HAR:vs20wraanu:bg_0:rw_c=0:COLLECT->doBonus(ind=0):2026-10-03T03-46-33-123Z; collect path only'
        return {'fields':{'ind':'0'},'domain':['0'],'selected':'0','default':None,
            'branch_signature':f'PRAGMATIC:bonus-continuation:{family}:bgt=69:minimal',
            'domain_basis':'Official demo client sends ind=0 for this exact continuation state',
            'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
            'selection_policy':'observed_continuation'}
    required={'ask','bgid','bgt','ch_k','ch_v','end','level','lifes','rw','status','wins','wins_mask'}
    if family!='bg_0' or not required<=set(fields) or set(fields)-required-{'ch_h','wi'}:return None
    if any(fields[k]!=v for k,v in {'ask':'0','bgid':'0','bgt':'69','end':'0','lifes':'1'}.items()):return None
    if not re.fullmatch(r'0(?:\.0+)?',fields['rw']):return None
    labels=fields['ch_k'].split(',');values=fields['ch_v'].split(',')
    statuses=fields['status'].split(',');wins=fields['wins'].split(',');masks=fields['wins_mask'].split(',')
    size=len(labels)
    if not 1<=size<=128 or any(len(v)!=size for v in [values,statuses,wins,masks]):return None
    indices=list(map(str,range(size)))
    if labels!=indices or values!=indices:return None
    if any(not re.fullmatch(r'0|[1-9][0-9]*',v) for v in statuses+[fields['level']]):return None
    if any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',v) for v in wins):return None
    if any(v not in {'h','s','l','f','w','m','be'} for v in masks):return None
    level=int(fields['level']);numbers=list(map(int,statuses))
    if level>=size:return None
    # Official client pre-reveals the bonus enhancer (be) before player picks.
    # It disables all positive-status cells; be is not part of ch_h history.
    player_statuses=[v for v,mask in zip(numbers,masks) if mask!='be' and v]
    if sorted(player_statuses)!=list(range(1,level+1)):return None
    if any(mask=='be' and (status!=1 or float(win)!=0) for mask,status,win in zip(masks,numbers,wins)):return None
    if any((status==0)!=(mask=='h') for status,mask in zip(numbers,masks)):return None
    if level:
        history=fields.get('ch_h','').split(',')
        if len(history)!=level or any(not re.fullmatch(r'0~(?:0|[1-9][0-9]*)',v) for v in history):return None
        picked=[int(v[2:]) for v in history]
        if len(set(picked))!=level or any(i>=size or masks[i]=='be' or numbers[i]!=n+1 for n,i in enumerate(picked)):return None
        if fields.get('wi')!=str(picked[-1]):return None
    elif 'ch_h' in fields:return None
    elif 'wi' in fields:
        if not re.fullmatch(r'0|[1-9][0-9]*',fields['wi']):return None
        initial=int(fields['wi'])
        if initial>=size or masks[initial]!='be':return None
    domain=[str(i) for i,status in enumerate(numbers) if status==0]
    if not domain:return None
    selected=domain[0] if override is None else str(override)
    if selected not in domain:raise ValueError('Bonus grid position is already revealed or outside the server domain')
    evidence='HAR:vs10bbextreme:bg_0:bgt=69:status->doBonus(ind):2026-10-03T00-31-17-027Z'
    return {'fields':{'ind':selected},'domain':domain,'selected':selected,'default':None,
        'branch_signature':f'PRAGMATIC:bonus-grid:bgt=69:level={level}:status='+','.join(statuses),
        'coverage_branch_signature':f'PRAGMATIC:bonus-grid:bg_0:bgt=69:size={size}:level={level}',
        'coverage_policy':'hidden-position-structural/v1',
        'domain_basis':'Official client selects a zero-based hidden position; selected positions have positive status and cannot be repeated',
        'contract_source':evidence,'contract_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
        'selection_policy':'first_available_test_choice' if override is None else 'explicit_override'}


def mystery_selection(response, symbol, override=None, purchase=False):
    """Book of Fallen: nine visible expanding symbols, explicit client ind."""
    if symbol != 'vs10bookfallen':
        return None
    if purchase:
        if response.get('action') != 'doSpin' or response.get('pur') != '0':
            return None
    elif (response.get('na') != 'm'
          or not re.fullmatch(r'[0-9]+~[0-9]+(?:\.[0-9]+)?~[0-9]+(?:,[0-9]+)*', str(response.get('psym', '')))):
        return None
    domain = list(map(str, range(9)))
    selected = domain[0] if override is None else str(override)
    if selected not in domain:
        raise ValueError('Expanding symbol choice outside the nine-symbol menu')
    evidence = 'Official Book of Fallen demo menu: nine symbols; HAR 2026-10-09T00-19-58-145Z: doMysteryScatter ind=8,2,5,7,4 -> ms=ind+3'
    return {'fields': {'ind': selected}, 'domain': domain, 'selected': selected, 'default': None,
            'branch_signature': 'PRAGMATIC:mystery-choice:vs10bookfallen:' + ('purchase=0:' if purchase else '') + 'choices=0,1,2,3,4,5,6,7,8',
            'domain_basis': 'Nine visible expanding symbols; remaining indices require accepted responses and terminal coverage',
            'contract_source': evidence, 'contract_sha256': hashlib.sha256(evidence.encode()).hexdigest(),
            'selection_policy': 'explicit_override' if override is not None else 'first_available_test_choice'}


def _empty_bank_auto(response, symbol):
    if symbol != 'vs20emptybank' or response.get('rs_m') != '3' or response.get('rs_c') != '1':
        return False
    group = _bonus_group({'na':'b', 'g':response.get('g','')})
    if group is None or group[0] != 's1':
        return False
    screen = group[1]
    required = {'mo','mo_t','mo_tv','mo_tw','reel_set','s','sa','sb','sh','st','sw'}
    if not required <= set(screen) or set(screen)-required-{'stf'}:
        return False
    if any(screen.get(k) != v for k,v in {'sh':'6','sw':'7','st':'rect','reel_set':'12'}.items()):
        return False
    for key,size in [('mo',42),('mo_t',42),('s',42),('sa',7),('sb',7)]:
        values = screen[key].split(',')
        if len(values) != size or any(not re.fullmatch(r'[a-z]+' if key=='mo_t' else r'[0-9]+',value) for value in values):
            return False
    return all(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',screen[k]) for k in ('mo_tv','mo_tw'))


def observed_paid_base(response, symbol):
    # 6 Jokers leaves rs_c=1 after a completed feature; it is not another respin.
    return (symbol == 'vs5magicdoor' and response.get('na') == 's'
            and response.get('bl') == '0' and response.get('rs_c') == '1'
            and response.get('trail') == 'dr~0'
            and all(response.get(k) in (None,'') for k in ('rs','rs_p','rs_m','rs_t','rs_more','fs','fsmax','g')))
