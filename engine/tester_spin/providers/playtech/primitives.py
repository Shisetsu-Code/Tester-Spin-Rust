"""GPAS contracts established from client constructors and live demo responses.

No title-specific tables; declarations without a recognized binding stay pending.
"""
import ast
import base64
import json
import re
import zlib
from copy import deepcopy
from .protocol import money
from .client_sources import compiled_pick_binding, compiled_default_cost_binding

COMMAND = "com.pt.casino.platform.game.GameCommand"
GAME_CLASS = "com.pt.gpas.platform.game.OgwCorosinGameCommand"
END = "BET_END_STATE_IDENTIFIER"


def decode_game_data(data, limit=8*1024*1024):
    if not isinstance(data, dict):
        raise ValueError("GAME_DATA_NOT_OBJECT")
    if data.get("_type") != "gpas:packed:zlib":
        return deepcopy(data)
    try:
        payload = data["payload"]
        if not isinstance(payload, str) or len(payload) > limit*2:
            raise ValueError("PACKED_LIMIT")
        decoder = zlib.decompressobj()
        body = decoder.decompress(base64.b64decode(payload, validate=True), limit+1)
        if len(body)>limit or not decoder.eof or decoder.unused_data:
            raise ValueError("PACKED_LIMIT_OR_TRUNCATED")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("PACKED_NOT_OBJECT")
        return result
    except (KeyError, TypeError, ValueError, zlib.error) as exc:
        raise ValueError("INVALID_PACKED_GAME_DATA") from exc


def client_contract(manifest, sources, adapter_config=None):
    text = "\n".join(sources)
    if GAME_CLASS not in text or not all(re.search(r"\b"+str(n)+r"\b",text) for n in (40021,48775)):
        raise ValueError("CLIENT_COMMAND_BINDING_UNKNOWN")
    setup = manifest.get("setup", {})
    legacy = setup.get("usesLegacyBetApi")
    if legacy is True and "GLU.game.bet" in text and "stakeCostUuid" in text:
        dialect = "legacy"
    elif legacy is not True and "GLU.game.playMoney" in text and (legacy is False or setup.get("useExtendedBetApi") is True or "GLU.game.bet" not in text):
        dialect = "modern"
    else:
        raise ValueError("CLIENT_BET_API_UNKNOWN")
    return {"adapter_maps": deepcopy(adapter_config or {}) if all(key in text for key in ("game_adapter","bet_features","bet_feature_types","toFeatureTypes")) else {}, "dialect":dialect, "class":GAME_CLASS, "entry_id":40021, "continuation_id":48775,
            "default_cost_binding": compiled_default_cost_binding(text) if dialect == 'modern' else {},
            "standard_start_bound": ('startingMode' in text and 'stakeCostName' in text and bool(re.search(r'!\s*[A-Za-z_$][\w$]*\([A-Za-z_$][\w$]*,["\']Standard["\']\)',text))),
            "base_selector": "default" if 'baseCostName:"default"' in text or "baseCostName:'default'" in text else None,
            "pick_bound": (bool(re.search(r'[\"\']pick[\"\']',text)) and "FGPickController" in text) or compiled_pick_binding(text)}


def discover_modes(configuration, contract, sources):
    game = configuration.get("game", {})
    costs = game.get("costConfiguration")
    factors = game.get("baseCostMultipliers", game.get("coinSizes"))
    if not isinstance(costs,list) or not costs or not isinstance(factors,list) or not factors:
        raise ValueError("STAKE_DECLARATION_MISSING")
    if not all(money(n) and n>0 for n in factors):
        raise ValueError("INVALID_MULTIPLIER_DOMAIN")
    active = game.get("activeBetOptions")
    if active is not None and (not isinstance(active,list) or not all(isinstance(n,str) for n in active)):
        raise ValueError("INVALID_ACTIVE_OPTIONS")
    text = "\n".join(sources)
    purchase_binding = bool(re.search(r"BuyFeature(?:Module|Controller|Configuration)",text))
    ante_binding = bool(re.search(r"ExtraBets?(?:Module|Controller|Configuration|Widget)",text)) or bool(re.search(r"extraBetNum\s*:\s*1",text))
    pot_domain=False
    for declared in re.finditer(r'new RegExp\((["\'])([^"\']{1,128})\1\)\.test\([A-Za-z_$][\w$]*\)',text):
        try:pattern=ast.literal_eval(declared[1]+declared[2]+declared[1])
        except (ValueError,SyntaxError):continue
        if pattern==r'^(BuyFeature\d+Pot)$':pot_domain=True
    descriptors={}
    for match in re.finditer(r"baseCostName:[\"']([^\"']+)[\"'],betParams:\{betType:[\w$.]+\.(DEFAULT|BONUS|EXTRA)([^}]{0,160})\}",text):
        kind={'DEFAULT':'SPIN','BONUS':'PURCHASE','EXTRA':'ANTE_BET'}[match[2]]
        if re.search(r'extraBetNum\s*:\s*[1-9]',match[3]):kind='ANTE_BET'
        descriptors.setdefault(match[1],set()).add(kind)
    scopes=game.get("namedScopes",{})
    if not isinstance(scopes,dict):raise ValueError("INVALID_NAMED_SCOPES")
    volatility_binding="currentVolatilitySuffix" in text or "VolatilityController" in text
    line_binding="winline" in text and "stakeCostUuid" in text and (contract['dialect']=="legacy" or ("stakeCostName" in text and "GLU.game.playMoney" in text))
    # A fixed-line client can expose one line stake. The line/serializer binding
    # and every declared row still have to match; cardinality is not a role.
    line_domain=line_binding and bool(costs) and all(isinstance(r,dict) and isinstance(r.get('parameters'),dict)
        and str(r.get('name','')).isdigit() and r['parameters'].get('winline')==r['name']
        and r['parameters'].get('startingMode')=='Standard' for r in costs)
    modes=[]; issues=[]; names=set(); ids=set()
    for index, row in enumerate(costs):
        if not isinstance(row,dict) or not money(row.get("cost")) or row["cost"]<=0:
            raise ValueError("INVALID_MODE_COST")
        name,identity = row.get("name"),row.get("uuid")
        if not isinstance(name,str) or not name or not isinstance(identity,str) or not identity or name in names or identity in ids:
            raise ValueError("INVALID_OR_DUPLICATE_MODE_IDENTITY")
        names.add(name);ids.add(identity)
        if active is not None and name not in active and not (index==0 and "default" in active):
            continue
        normalized=name.casefold()
        scope=scopes.get(name,{})
        if not isinstance(scope,dict):raise ValueError("INVALID_NAMED_SCOPE")
        scoped=scope.get('betType')=='default' and scope.get('featureType')==name
        parameters=row.get('parameters',{})
        standard=(contract.get('standard_start_bound') is True and sum(isinstance(c,dict) and isinstance(c.get('parameters'),dict) and c['parameters'].get('startingMode')=='Standard' for c in costs)==1 and isinstance(parameters,dict)
                  and parameters.get('startingMode')=='Standard' and type(parameters.get('startingPlays')) in (str,int) and parameters.get('startingPlays') in ('1',1)
                  and set(parameters)<={'startingMode','startingPlays','winline','discountable','evalPayout','disableBCMValidation'})
        declared_kinds=descriptors.get(name,set())
        from .adapter_config import mapped_kind
        mapped=mapped_kind(name,contract.get('adapter_maps',{}))
        if mapped:declared_kinds=set(declared_kinds)|{mapped}
        if len(declared_kinds)==1:
            kind=next(iter(declared_kinds))
        elif len(declared_kinds)>1:
            kind='UNKNOWN_FEATURE';issues.append('STAKE_KIND_CONFLICT:'+name)
        elif (normalized=="extra" or (scoped and re.fullmatch(r"extra(?:[0-9]+|x[0-9]+(?:low|mid|high)?)",normalized))) and ante_binding:
            kind="ANTE_BET"
        elif (normalized in {"bf","buyfeature"} or ((scoped or game.get("featureBetEnabled") is True) and (re.fullmatch(r"(?:bf[0-9]+|buyfeature(?:[0-9]+x|extra))",normalized) or (pot_domain and re.fullmatch(r"buyfeature[0-9]+pot",normalized))))) and purchase_binding:
            kind="PURCHASE"
        elif (contract.get('default_cost_binding',{}).get('profile') == 'compiled-default-cost-name/v1'
              and len(costs) == 1 and isinstance(parameters,dict)
              and parameters.get('startingPlays') in ('1', 1) and type(parameters.get('startingPlays')) in (str,int)
              and isinstance(parameters.get('startingMode'),str) and bool(parameters['startingMode'])
              and set(parameters)<={'startingMode','startingPlays','winline','discountable','evalPayout','disableBCMValidation','maxBaseCostMultiplier'}):
            kind="SPIN"
        elif standard or line_domain or (scoped and volatility_binding and re.fullmatch(r"default(?:low|mid|high)",normalized)) or normalized in {"default","base"}:
            kind="SPIN"
        else:
            kind="UNKNOWN_FEATURE";issues.append("UNBOUND_STAKE_MODE:"+name)
        modes.append({"id":identity,"name":name,"kind":kind,"selector":scope.get("featureType",("default" if standard else (contract.get("base_selector") or name)) if kind=="SPIN" and index==0 else name),"cost":row["cost"],
                      "bet_type":scope.get("betType","default"),"multiplier":min(factors),"declaration":deepcopy(row),"server_declared":True,"observed":True})
    if not any(m["kind"]=="SPIN" for m in modes):issues.append("BASE_MODE_UNBOUND")
    if active is not None:
        for name in active:
            if name not in names and not (name=="default" and costs):issues.append("ACTIVE_OPTION_UNBOUND:"+name)
    domains={key:{"complete":not issues,"source":"fresh_session.costConfiguration+client_binding+activeBetOptions",
                  "options":[m["id"] for m in modes if m["kind"]==kind]} for key,kind in (("purchase","PURCHASE"),("ante","ANTE_BET"))}
    return {"modes":modes,"domains":domains,"unresolved":issues}


def paid_option_declaration(plan):
    """Normalize GPAS's complete cost domain, never a per-title lookup.

    Retain unknown rows so an incomplete interpretation cannot silently lower
    the advertised count. Ordinary base stakes remain covered by mode gates.
    """
    categories = {'PURCHASE':'bonus_purchase', 'ANTE_BET':'ante_bet',
                  'FEATURE_SPIN':'special_mode', 'BET_MODE':'special_mode'}
    options = []
    issues = list(plan.get('unresolved', []))
    for mode in plan.get('modes', []):
        kind = mode.get('kind')
        if kind == 'SPIN':
            continue
        category = categories.get(kind, 'unknown')
        if category == 'unknown':
            issues.append('PAID_OPTION_KIND_UNBOUND:' + str(mode.get('id')))
        options.append({'id':mode['id'], 'name':mode.get('name',mode['id']),
                        'category':category, 'cost':mode.get('cost'),
                        'multiplier':mode.get('multiplier')})
    if not any(m.get('kind') == 'SPIN' for m in plan.get('modes', [])):
        issues.append('BASE_MODE_UNBOUND')
    return {'primitive': {'id':'playtech.gpas.cost-domain','version':1},
            'source':'fresh_session.costConfiguration+client_binding+activeBetOptions',
            'options':options, 'complete':not issues,
            'unresolved':list(dict.fromkeys(issues))}


def entry_command(mode, contract):
    if mode["kind"]=="UNKNOWN_FEATURE":raise ValueError("UNBOUND_STAKE_MODE")
    amount=mode["cost"]*mode["multiplier"]
    data={"_type":contract["class"],"ID":contract["entry_id"],"parameters":[]}
    if contract["dialect"]=="legacy":
        data.update(bet=amount,stakeCostUuid=mode["id"],baseCostMultiplier=mode["multiplier"])
        return {"_type":COMMAND,"gameData":data,"betType":"default"}
    return {"_type":COMMAND,"gameData":data,"autoplay":False,"betCost":amount,"betType":mode.get("bet_type","default"),"featureType":mode["selector"]}


class PickState:
    def __init__(self, target=None):
        self.consumed={}; self.offered={}; self.selected={}; self.target=dict(target or {});self.target_applied=set()

    def parameters(self, data, bound):
        for stack in data.get("playStack",[]):
            for payout in stack.get("lastPlayInModeData",{}).get("listPickData",{}).get("payoutResults",[]):
                index=payout.get("context",{}).get("uiIndex")
                if type(index) is int:
                    self.consumed.setdefault(stack.get("round"),set()).add(index)
        phase=data.get("nextRound")
        active=any(s.get("round")==phase and s.get("modeType")=="LIST_PICK" and s.get("remainingPlayCount",0)>0 for s in data.get("playStack",[]))
        if not active:return []
        if not bound:raise ValueError("PICK_COMMAND_NOT_BOUND")
        options=data.get("listPickPlayerPickOptions")
        if not isinstance(options,list) or not options or not all(isinstance(o,dict) and type(o.get("index")) is int for o in options):
            raise ValueError("PICK_DOMAIN_UNKNOWN")
        offered={o["index"] for o in options}; self.offered.setdefault(phase,set()).update(offered)
        available=sorted(offered-self.consumed.get(phase,set()))
        if not available:raise ValueError("NO_UNCONSUMED_PICK")
        preferred=self.target.get(phase)
        index=preferred if phase not in self.target_applied and preferred in available else available[0]
        self.target_applied.add(phase)
        self.selected.setdefault(phase,set()).add(index)
        return [{"key":"pick","value":str(index)}]

    def pending(self):
        return {phase:sorted(options-self.selected.get(phase,set())) for phase,options in self.offered.items() if options-self.selected.get(phase,set())}


class RoundLedger:
    def __init__(self, balance_before, identity, cost):
        self.before=balance_before;self.identity=identity;self.cost=cost
        self.count=0;self.wins=0;self.closed=False;self.data={}

    def accept(self, message):
        stake,win=message.get("stakeAmount"),message.get("winAmount")
        if not money(stake) or not money(win):raise ValueError("INVALID_SETTLEMENT_MONEY")
        if stake != (self.cost if not self.count else 0):raise ValueError("UNEXPECTED_CHARGE")
        if "betCost" in message and message["betCost"]!=stake:raise ValueError("BET_COST_MISMATCH")
        data=decode_game_data(message.get("gameData"))
        if (not self.count or "stakeCostUuid" in data) and data.get("stakeCostUuid")!=self.identity:
            raise ValueError("STAKE_UUID_MISMATCH")
        self.count+=1;self.wins+=win;self.data=data
        self.closed=message.get("gameRoundClosed") is True and data.get("nextRound")==END
        if self.closed and data.get("totalWinAmount")!=self.wins:raise ValueError("CUMULATIVE_WIN_MISMATCH")
        return data

    def verify(self, balance_after):
        return bool(self.count and self.closed and money(self.before) and money(balance_after) and balance_after==self.before-self.cost+self.wins)
