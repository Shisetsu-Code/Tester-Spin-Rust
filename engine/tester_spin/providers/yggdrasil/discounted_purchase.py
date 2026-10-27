"""SDK random-level purchase with progress-dependent price, never nine extra buys.

The learned wire family declares BUY_A_BONUS[_percent] for one random-level
card and MAX_BUY_A_BONUS for the separate maximum-level card. Require the
whole server price lattice and denomination contract before grouping it.
No game identifier or title participates in recognition.
"""
from decimal import Decimal
import re

BASE="BUY_A_BONUS"
PATTERN=re.compile(r"BUY_A_BONUS_(?:[1-9]0)\Z")
COIN_KEY=re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{5}\Z")
SOURCE="sdk.random_level_discount/server.Modes/playerState.bonusProgress/v1"

def group_prices(modes,templates,unresolved):
    from .runtime import number
    aliases=[name for name in modes if name.startswith(BASE+"_")]
    if not aliases:return modes,{},False
    family=[BASE]+aliases
    expected={BASE+"_"+str(n) for n in range(10,100,10)}
    valid=(set(aliases)==expected and BASE in templates and "MAX_BUY_A_BONUS" in templates and all(k in templates for k in family))
    if valid:
        base=templates[BASE]
        for cmd in aliases:
            percent=int(cmd.rsplit("_",1)[1]);template=templates[cmd]
            valid=valid and set(modes[cmd])=={"coinsPerBet"} and template["coin"]==base["coin"] and template.get("lines")==base.get("lines") and number(template["amount"])==number(base["amount"])*(100-percent)/100
    if not valid:
        for cmd in family:
            templates.pop(cmd,None);unresolved[cmd]="Discounted purchase contract not proven; price states are not independent buys"
        return modes,{},False
    variants={cmd:{"discount_percent":0 if cmd==BASE else int(cmd.rsplit("_",1)[1]),"template":dict(templates[cmd])} for cmd in family}
    for cmd in aliases:templates.pop(cmd)
    return {cmd:options for cmd,options in modes.items() if cmd not in aliases},{BASE:variants},True

def selected_price(variants,payload,coin):
    from .runtime import Unsupported,number
    data=payload.get("data") if isinstance(payload,dict) else None
    if not isinstance(data,dict) or ("initialized" in data and data["initialized"] is not True):raise Unsupported("Player state not initialized")
    state=data.get("playerState")
    progress=state.get("bonusProgress") if isinstance(state,dict) else None
    if not isinstance(progress,dict) or len(progress)>4096:raise Unsupported("Missing typed purchase progress")
    for key,value in progress.items():
        if not isinstance(key,str) or not COIN_KEY.fullmatch(key) or type(value) is not int or value not in range(0,101,10):raise Unsupported("Unknown purchase progress domain")
    key=format(number(coin),".5f")
    if number(key)!=number(coin):raise Unsupported("Coin cannot be represented by SDK progress key")
    percent=progress.get(key,0)
    selected=[entry for entry in variants.values() if entry["discount_percent"]==percent]
    if len(selected)!=1:raise Unsupported("Current progress has no advertised purchase price")
    return dict(selected[0]["template"]),{"source":SOURCE,"coin":coin,"discount_percent":percent,"wire_command":selected[0]["template"]["cmd"]}

def archive_price_variants(result,pending,migrations,source):
    """Remove obsolete price-state obligations; retain evidence and sample quota."""
    import copy
    from .runtime import number
    domain=result.feature_domains.get("purchase",{})
    if not isinstance(domain,dict) or domain.get("complete") is not True or domain.get("source")!=SOURCE:return
    parent=next((m for m in result.discovered_modes if isinstance(m,dict) and m.get("id")==BASE and m.get("kind")=="PURCHASE" and m.get("server_declared") is True and m.get("source")=="server.game.cfg.Modes" and m.get("coverage_required") is True),None)
    if parent is None or BASE not in domain.get("options",[]):return
    variants=parent.get("price_variants")
    expected={BASE}|{BASE+"_"+str(n) for n in range(10,100,10)}
    if not isinstance(variants,dict) or set(variants)!=expected:return
    try:
        base=variants[BASE]["template"]
        for cmd,item in variants.items():
            percent=0 if cmd==BASE else int(cmd.rsplit("_",1)[1]);t=item["template"]
            if item["discount_percent"]!=percent or t["cmd"]!=cmd or t["coin"]!=base["coin"] or t.get("lines")!=base.get("lines") or number(t["amount"])!=number(t["coin"])*number(t["coins"]) or number(t["amount"])!=number(base["amount"])*(100-percent)/100:return
    except (KeyError,TypeError,ValueError):return
    for cmd in sorted(expected-{BASE}):
        prior=pending.get(cmd)
        if not isinstance(prior,dict) or prior.get("kind")!="PURCHASE" or prior.get("required_options")!=[cmd]:continue
        try:target=max(1,int(prior.get("required_samples") or 1),int(parent.get("required_samples") or 1))
        except (ValueError,TypeError):continue
        parent["required_samples"]=target
        migrations.append({"policy":"yggdrasil-discount-price-to-purchase/v1","previous_id":cmd,"previous":copy.deepcopy(prior),"replacement_id":BASE,"replacement_source":source,"role_source":SOURCE,"required_samples":target,"price_variant":copy.deepcopy(variants[cmd])})
        del pending[cmd]
