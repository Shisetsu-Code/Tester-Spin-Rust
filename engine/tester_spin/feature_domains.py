"""Category-specific declarations. Missing data never proves an empty domain."""
import math
import json
import re


def _domain(source, options):
    return {'complete': True, 'source': source, 'options': list(dict.fromkeys(str(v) for v in options))}


def _ids(value):
    return isinstance(value, list) and all(isinstance(v,(str,int)) and not isinstance(v,bool) and (not isinstance(v,str) or bool(v.strip())) for v in value)


def _declaration_json(raw):
    def object_from_pairs(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate declaration key')
            result[key]=value
        return result
    # doInit serializes JS object keys without quotes. Add key quotes only;
    # JSON still rejects expressions, identifiers and executable syntax.
    quoted=re.sub(r'([{,]\s*)([A-Za-z_$][\w$]*)(\s*:)',r'\1"\2"\3',raw)
    return json.loads(quoted,object_pairs_hook=object_from_pairs)


def initialization_domains(provider, data, modes, *, client_profile=None):
    domains={}
    if provider == 'rubyplay':
        from tester_spin.providers.rubyplay.paid_domains import initialization_domains as rubyplay_domains
        return rubyplay_domains(data, modes, client_profile)
    if provider=='pragmatic':
        raw=data.get('purInit')
        if isinstance(raw,str):
            valid=True;prices=[]
            if raw.strip():
                try:
                    parsed=_declaration_json(raw)
                    if not isinstance(parsed,list):
                        valid=bool(re.fullmatch(r'\s*[0-9]+(?:\.[0-9]+)?(?:\s*,\s*[0-9]+(?:\.[0-9]+)?)*\s*',raw))
                        prices=[float(v) for v in raw.split(',')] if valid else []
                    elif not all(isinstance(v,dict) and 'bet' in v for v in parsed):
                        valid=False
                    else:
                        prices=[v['bet'] for v in parsed]
                        valid=all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 for v in prices)
                except ValueError:
                    valid=bool(re.fullmatch(r'\s*[0-9]+(?:\.[0-9]+)?(?:\s*,\s*[0-9]+(?:\.[0-9]+)?)*\s*',raw))
                    prices=[float(v) for v in raw.split(',')] if valid else []
            valid=valid and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 for v in prices)
            enabled=data.get('purInit_e')
            tokens=[]
            if enabled is not None:
                if not isinstance(enabled,str):valid=False
                else:
                    tokens=[v.lower() for v in re.split(r'[,;|~ ]+',enabled.strip()) if v]
                    valid=valid and all(v in {'0','0.0','1','1.0','true','false','on','off','yes','no','null','none'} for v in tokens)
                    if prices and tokens and len(prices)!=len(tokens):valid=False
            if valid:
                enabled_ids=[f'PURCHASE_{i+1}' for i in range(max(len(prices),len(tokens)))
                             if not tokens or tokens[i] not in {'0','0.0','false','off','no','null','none'}]
                domains['purchase']=_domain('doInit.purInit/purInit_e',enabled_ids)
            else:
                domains['purchase']={'complete':False,'source':'doInit.purInit/purInit_e','options':[], 'reason':'UNRECOGNIZED_PURCHASE_DECLARATION'}
        raw=data.get('bls')
        if isinstance(raw,str) and raw.strip():
            try: values=[float(v) for v in raw.split(',')]
            except ValueError:values=[]
            if values and all(math.isfinite(v) and v>0 for v in values):
                domains['ante']=_domain('doInit.bls',[f'ANTE_BET_{i}' for i in range(1,len(values))])
    elif provider=='bgaming':
        options=data.get('options') or {}
        feature=options.get('feature_options') or {} if isinstance(options,dict) else {}
        values=feature.get('feature_multipliers') if isinstance(feature,dict) else None
        if isinstance(values,dict):
            raw=[v for value in values.values() for v in (value.values() if isinstance(value,dict) else [value])]
            disabled=feature.get('disabled_features')
            valid_disabled=(disabled is None or isinstance(disabled,list) or
                            isinstance(disabled,dict) and all(isinstance(v,bool) for v in disabled.values()))
            if valid_disabled and all(not isinstance(v,dict) or bool(v) for v in values.values()) and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0 for v in raw):
                from tester_spin.providers.bgaming.runtime import discover_purchase_modes
                purchases=discover_purchase_modes(data)
                categories={'purchase':[], 'ante':[]}
                for mode in purchases:
                    name=mode['name']
                    category='ante' if 'chance' in name.lower().split('_') else 'purchase'
                    categories[category].append(name+(':'+str(mode['level']) if mode['level'] is not None else ''))
                for category,ids in categories.items():
                    domains[category]=_domain('init.options.feature_options.feature_multipliers',ids)
            else:
                domains['purchase']={'complete':False,'source':'init.options.feature_options.feature_multipliers','options':[], 'reason':'UNRECOGNIZED_FEATURE_DECLARATION'}
    elif provider=='3oaks':
        context=data.get('context') or {};settings=data.get('settings') or {}
        values=context.get('available_buy_bonus')
        if _ids(values):domains['purchase']=_domain('start.context.available_buy_bonus',values)
        # Other formats invalidate a claim of complete purchase absence.
        if context.get('available_buy_freespins'):
            domains.pop('purchase',None)
        if settings.get('ante_bet')==[] and not context.get('available_boosters'):
            domains['ante']=_domain('start.settings.ante_bet',[])
    elif provider=='hacksaw':
        from tester_spin.providers.hacksaw.runtime import BONUS_ID, discover_modes
        values=data.get('bonusGames')
        source='authenticate.bonusGames/get_featureBuyItemType'
        valid=(isinstance(values,list) and all(isinstance(v,dict) and
               isinstance(v.get('bonusGameId'),(str,int)) and not isinstance(v.get('bonusGameId'),bool)
               and BONUS_ID.fullmatch(str(v['bonusGameId'])) for v in values))
        if valid:
            declared=discover_modes(data)
            if any(m['kind']=='UNKNOWN_FEATURE' for m in declared):
                for category in ('purchase','feature_spin'):
                    domains[category]={'complete':False,'source':source,'options':[], 'reason':'UNKNOWN_FEATURE_ITEM_TYPE'}
            else:
                for category,kind in [('purchase','PURCHASE'),('feature_spin','FEATURE_SPIN')]:
                    domains[category]=_domain(source,[m['buyBonus'] for m in declared if m['kind']==kind])
        elif values is not None:
            domains['purchase']={'complete':False,'source':source,'options':[], 'reason':'INVALID_BONUS_GAMES'}
    elif provider=='belatra':
        buy=data.get('buyBonus')
        if isinstance(buy,dict):
            values=buy.get('buyTotalBetK')
            if isinstance(values,dict):domains['purchase']=_domain('enter.gs.buyBonus.buyTotalBetK',values.keys())
            elif isinstance(values,list):domains['purchase']=_domain('enter.gs.buyBonus.buyTotalBetK',range(len(values)))
        vip=data.get('vipMode')
        if isinstance(vip,dict) and isinstance(vip.get('vipBetK'),(int,float)) and not isinstance(vip.get('vipBetK'),bool):
            value=vip['vipBetK']
            if math.isfinite(value) and value>0:domains['ante']=_domain('enter.gs.vipMode.vipBetK',['vipOn=1'] if value>1 else [])
    return domains
