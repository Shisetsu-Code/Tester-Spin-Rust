"""Proof of a resolved current menu, without asserting every gamble path ran."""
import json
from decimal import Decimal,InvalidOperation
from pathlib import Path
SCOPE="server_paid_domain_with_resolved_zero_cost_controls/v1"
PROTOCOL="yggdrasil-current-zero-cost-menu/v1"

def _load(path):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):return None

def resolved_menu(result,mode_id,path,payload,validated):
    if result.provider!='yggdrasil' or not isinstance(payload,dict):return False
    choice=payload.get('choices')
    if not isinstance(choice,dict) or choice.get('protocol')!=PROTOCOL or choice.get('selected') is not None:return False
    domain=choice.get('available')
    if not isinstance(domain,list) or len(domain)<2 or not all(isinstance(v,str) and v for v in domain) or len(set(domain))!=len(domain):return False
    if not all(result.feature_domains.get(k,{}).get('complete') is True for k in ('purchase','ante')):return False
    if not any(isinstance(m,dict) and m.get('id')==mode_id and m.get('validated') is True and m.get('coverage_scope')==SCOPE and m.get('execution_state')=='PROVEN_TERMINAL' and m.get('evidence_level')=='REMOTE_EXECUTION' for m in result.discovered_modes):return False
    ancestor=next((p for p in path.parents if p.resolve() in validated),None)
    if ancestor is None:return False
    proof=_load(ancestor/'return-to-base.json')
    if not isinstance(proof,dict) or proof.get('status')!='CONFIRMED' or proof.get('required')!=2 or proof.get('consecutive_base',0)<2:return False
    try:prior=max(b['step'] for b in payload['bets'])
    except (KeyError,TypeError,ValueError):return False
    for reply_path in path.parent.glob('step-*-response.json'):
        reply=_load(reply_path)
        if not isinstance(reply,dict) or reply.get('round_ref')!=payload.get('round_ref') or not payload.get('round_ref') or reply.get('transition_validated') is not True:continue
        selected=reply.get('choices',{})
        if not isinstance(selected,dict) or selected.get('protocol')!=PROTOCOL or selected.get('available')!=domain or selected.get('selected') not in domain:continue
        request=_load(reply_path.with_name(reply_path.name.replace('-response','-request')))
        try:
            step=int(request['step'])
            if Decimal(str(request['amount']))!=0 or request['cmd']!=selected['selected'] or step!=prior+1:continue
            if not any(b.get('step')==step and b.get('command')==request['cmd'] for b in reply['bets']):continue
        except (KeyError,TypeError,ValueError,InvalidOperation):continue
        return True
    return False
