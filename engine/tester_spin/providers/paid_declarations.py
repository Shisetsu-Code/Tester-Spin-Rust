"""Translate provider primitives' explicit domains into the universal contract.

No title lists and no prices used to guess action roles. Missing category,
unknown role or unbound selector leaves the entire declaration incomplete.
"""
import json
from pathlib import Path

# These are protocol domains, not a list of games or their purchases.
DOMAINS = {key:('purchase','ante') for key in
           ('pragmatic','bgaming','belatra','3oaks','ka_gaming','redtiger','rubyplay','yggdrasil','1spin4win','playtech')}
DOMAINS.update(hacksaw=('purchase','feature_spin'), nolimit_city=('purchase','feature_spin'))
EVIDENCE = {
 'pragmatic':('discovery/doInit.response.raw',),
 'bgaming':('init-response.json',),
 'belatra':('bootstrap/enter.response.raw.txt',),
 '3oaks':('bootstrap/*start*.response.raw.json','*start*.response.raw.json'),
 'hacksaw':('authenticate.response.raw.json',),
 'nolimit_city':('bootstrap/0001.response.json','capture.har'),
 'ka_gaming':('bootstrap/*startGame*.response.raw.json','*startGame*.response.raw.json','feature-declaration.json'),
 'redtiger':('bootstrap/settings.response.json',),
 'rubyplay':('bootstrap/**/init-response.json','bootstrap/init-response.json','bootstrap/paid-client-profile.json'),
 'yggdrasil':('current-server-configuration.json',),
 '1spin4win':('**/runtime-spec.json',),
 'playtech':('ngm-har-contracts.json','execution-plan.json'),
}
KINDS={'PURCHASE':'purchase','PURCHASE_BRANCH':'purchase','ANTE_BET':'ante',
       'FEATURE_SPIN':'feature_spin','BET_MODE':'special','STATE_SWITCH':'special'}
CATEGORIES={'purchase':'bonus_purchase','ante':'ante_bet','feature_spin':'special_mode','special':'special_mode'}


def aliases(mode):
    found={str(mode['id'])} if mode.get('id') is not None else set()
    found.update(str(v) for v in mode.get('required_options',[]) if v is not None)
    for key in ('selected_mode','buyBonus','feature_buy','selector','name'):
        if mode.get(key) is not None:found.add(str(mode[key]))
    request=mode.get('request') or {};purchase=mode.get('purchase') or {}
    name=mode.get('purchased_feature') or mode.get('purchase_name') or request.get('purchased_feature') or purchase.get('name')
    level=mode.get('purchased_feature_level',mode.get('purchase_level',mode.get('feature_level',request.get('purchased_feature_level',purchase.get('level')))))
    if name:found.add(str(name)+(':'+str(level) if level is not None else ''))
    return found


def declare_adapter_paid_options(result):
    if result.provider not in DOMAINS or not result.run_dir:
        return False
    root=Path(result.run_dir);root.mkdir(parents=True,exist_ok=True)
    domains=result.feature_domains;issues=[];options=[];matched=set()
    def category(mode):
        if result.provider=='bgaming' and mode.get('kind')=='PURCHASE':
            # BGaming serializes both via purchased_feature. Roles come from
            # its explicit initialization primitive, not the transport name.
            ante=domains.get('ante',{})
            if (ante.get('source')=='init.options.feature_options.feature_multipliers'
                    and set(str(v) for v in ante.get('options',[])) & aliases(mode)):
                return 'ante'
        return KINDS.get(str(mode.get('kind','')))
    required=set(DOMAINS[result.provider]) | (set(domains) & set(CATEGORIES))
    for key in sorted(required):
        domain=domains.get(key,{})
        if (domain.get('complete') is not True or not domain.get('source')
                or not isinstance(domain.get('options'),list)):
            issues.append('PAID_DOMAIN_INCOMPLETE:'+key)
        values=domain.get('options',[])
        if not isinstance(values,list):values=[]
        if len({str(v) for v in values})!=len(values):issues.append('PAID_DOMAIN_DUPLICATE:'+key)
        for value in values:
            selector=str(value)
            modes=[m for m in result.discovered_modes if category(m) == key and selector in aliases(m)]
            # Belatra's ante selector is an explicit choice matrix.
            if key=='ante':
                modes += [m for m in result.discovered_modes if m.get('id')=='BELATRA_START_SELECTOR_MATRIX' and selector in aliases(m)]
            identities=sorted({str(m['id']) for m in modes if m.get('id')})
            if not identities:issues.append('PAID_SELECTOR_UNBOUND:'+key+':'+selector)
            matched.update(identities)
            options.append({'id':key+':'+selector,'selector':selector,'category':CATEGORIES[key],
                            'execution_ids':identities,'source':domain.get('source'),
                            'costs':[{k:m[k] for k in ('cost','feature_multiplier','price_multiplier','stake','cost_multiplier') if k in m} for m in modes]})
    for mode in result.discovered_modes:
        kind=str(mode.get('kind',''));identity=str(mode.get('id',''))
        if kind=='UNKNOWN_FEATURE' or kind in KINDS and identity not in matched:
            issues.append('PAID_MODE_OUTSIDE_DECLARATION:'+identity)
    # Persist the exact inputs as well as existing initialization captures.
    snapshot=root/'paid-domain-input.json'
    snapshot.write_text(json.dumps({'domains':domains,'modes':result.discovered_modes},ensure_ascii=False,indent=2),encoding='utf-8')
    evidence=[]
    for pattern in EVIDENCE.get(result.provider,()):
        evidence.extend(str(p.relative_to(root)) for p in sorted(root.glob(pattern)) if p.is_file())
    evidence=list(dict.fromkeys(evidence))
    if not evidence:issues.append('PAID_INITIALIZATION_CAPTURE_MISSING')
    from tester_spin.paid_options import write_paid_option_inventory
    write_paid_option_inventory(result,primitive={'id':result.provider+'.declared-domains','version':1},
        source='provider_protocol_primitive.explicit_domains',options=options,complete=not issues,
        unresolved=issues,evidence_files=[*evidence,'paid-domain-input.json'])
    return True
