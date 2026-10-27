"""Reviewed GPAS declarations and settlement facts, without purchase guesses.

These functions accept current server messages as well as offline observations.
They never submit commands or treat historical coverage as a successful run.
"""
from copy import deepcopy
import re


def money(value):
    return isinstance(value,int) and not isinstance(value,bool) and value>=0


def _merge_configuration(left,right):
    # GPAS client merge: recurse through objects, replace arrays/scalars.
    if not isinstance(left,dict) or not isinstance(right,dict):return deepcopy(right)
    result=deepcopy(left)
    for key,value in right.items():
        result[key]=_merge_configuration(result[key],value) if key in result else deepcopy(value)
    return result


def resolve_configuration(rows,context):
    """Match every scope key and merge matching rows in server order.

    Mirrors the captured GPAS configuration cache, including array-valued scopes
    and replacement (not concatenation) of lists. Does not imply a paid feature.
    """
    if not isinstance(rows,list) or not isinstance(context,dict) or not context:
        raise ValueError("Configuración o contexto inválido")
    found=False;resolved={}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("scope"),dict) or not isinstance(row.get("content"),dict):
            raise ValueError("Ámbito de configuración malformado")
        scope=row["scope"]
        if all(key in context and (context[key] in value if isinstance(value,list) else context[key]==value) for key,value in scope.items()):
            resolved=_merge_configuration(resolved,row["content"]);found=True
    if not found:raise ValueError("No hay configuración que coincida con el contexto")
    return resolved


def _effective_modes(rows):
    contexts={};modes=[];unresolved=[]
    stake_fields=("baseCostMultipliers","defaultBaseCostMultiplier","coinSizes","defaultCoinSize","minBet","maxBet")
    capability_fields=("featureBetEnabled","extraBetEnabled","powerPlayEnabled","activeBetOptions")
    for context in ("default","freespin"):
        try:resolved=resolve_configuration(rows,{"betType":context})
        except ValueError:
            unresolved.append("CONTEXT_NOT_RESOLVED:"+context);continue
        game=resolved.get("game",{})
        if not isinstance(game,dict):unresolved.append("INVALID_GAME_CONFIG");continue
        limits=resolved.get("limits",{})
        if not isinstance(limits,dict):unresolved.append("INVALID_LIMITS");limits={}
        contexts[context]={"limits":deepcopy(limits),"stake_domain":{k:deepcopy(game[k]) for k in stake_fields if k in game},
                           "capabilities":{k:deepcopy(game[k]) for k in capability_fields if k in game}}
        costs=game.get("costConfiguration",[])
        if not isinstance(costs,list):unresolved.append("INVALID_COST_CONFIGURATION");continue
        for cost in costs:
            if not isinstance(cost,dict) or not money(cost.get("cost")):
                unresolved.append("INVALID_COST");continue
            identifier=cost.get("uuid")
            if not isinstance(identifier,str) or not identifier:
                unresolved.append("COST_ID_MISSING");continue
            existing=next((mode for mode in modes if isinstance(identifier,str) and identifier and mode["declaration"]==cost),None)
            if existing is not None:
                existing["contexts"].append(context);continue
            parameters=cost.get("parameters",{})
            base=isinstance(parameters,dict) and parameters.get("startingMode")=="Standard" and str(parameters.get("startingPlays"))=="1"
            modes.append({"declaration":deepcopy(cost),"contexts":[context],
                          "classification":"base_candidate" if base else "unclassified","executable":False})
    return contexts,modes,unresolved


def configuration_domains(rows):
    result={"costs":[],"purchase":{"declaration_state":"UNKNOWN","options":[]},
            "antebet":{"declaration_state":"UNKNOWN","options":[]},"unresolved":[]}
    if not isinstance(rows,list):
        result["unresolved"].append("INVALID_CONFIGURATION");return result
    for row in rows:
        if not isinstance(row,dict):result["unresolved"].append("INVALID_SCOPE");continue
        content=row.get("content",{});game=content.get("game",{}) if isinstance(content,dict) else {}
        if not isinstance(game,dict):result["unresolved"].append("INVALID_GAME_CONFIG");continue
        costs=game.get("costConfiguration")
        if costs is None:continue
        if not isinstance(costs,list):result["unresolved"].append("INVALID_COST_CONFIGURATION");continue
        for cost in costs:
            if not isinstance(cost,dict):result["unresolved"].append("INVALID_COST");continue
            item={**deepcopy(cost),"scope":deepcopy(row.get("scope",{}))}
            item["executable"]=False  # Price declaration alone does not bind an action.
            if not money(cost.get("cost")):result["unresolved"].append("INVALID_COST")
            result["costs"].append(item)
    if not result["costs"]:result["unresolved"].append("COST_CONFIGURATION_NOT_OBSERVED")
    contexts,modes,issues=_effective_modes(rows)
    result.update(contexts=contexts,effective_modes=modes)
    result["unresolved"].extend(issues)
    return result


def decision_evidence(value,path="",depth=0):
    if depth>40:return []
    found=[]
    if isinstance(value,dict):
        for key,item in value.items():
            nested=(path+"." if path else "")+key
            if re.search(r"choice|option|allowed|selected|remainingPlayCount|newPlayCount",key,re.I):
                found.append({"path":nested,"value":deepcopy(item)})
            else:found.extend(decision_evidence(item,nested,depth+1))
    elif isinstance(value,list):
        for index,item in enumerate(value):found.extend(decision_evidence(item,path+"."+str(index),depth+1))
    return found


def round_evidence(message,balance_before=None,balance_after=None):
    data=message.get("gameData",{})
    data=data if isinstance(data,dict) else {}
    stake=message.get("stakeAmount");win=message.get("winAmount")
    arithmetic=all(money(x) for x in (balance_before,balance_after,stake,win))
    if arithmetic:arithmetic=balance_before-stake+win==balance_after
    if "betCost" in message and (not money(message["betCost"]) or message["betCost"]!=stake):arithmetic=False
    if "stake" in data and (not money(data["stake"]) or data["stake"]!=stake):arithmetic=False
    if "totalWinAmount" in data and (not money(data["totalWinAmount"]) or data["totalWinAmount"]!=win):arithmetic=False
    terminal=message.get("gameRoundClosed") is True and data.get("nextRound")=="BET_END_STATE_IDENTIFIER"
    return {"settlement_verified":bool(arithmetic and terminal),"terminal_observed":terminal,
            "continuation":{k:deepcopy(data[k]) for k in ("nextRound","requestParameters","currentTitleState","currentCycleState","currentSharedState") if k in data},
            # Captured GPAS round serializer declares these independently of money.
            # Preserve observations only: no price-derived identity or action binding.
            "stake_selection":{k:deepcopy(data[k]) for k in ("stakeCostUuid","stakeCostName","stakeCostParameters","baseCostMultiplier") if k in data},
            "stake":stake,"win":win,"decisions":decision_evidence(data),"certifies_game_ok":False}


def inspect_evidence(report,symbol):
    if (not isinstance(report,dict) or report.get("schema")!="aislador/playtech-evidence/v1"
        or report.get("provider")!="playtech" or report.get("certifies_game_ok") is not False
        or report.get("coverage")!="observations_only"):
        raise ValueError("Evidencia Playtech incompatible o con certificación no permitida")
    # Mixed sessions cannot silently attribute another title's declarations.
    if report.get("game_codes") != [symbol]:raise ValueError("La captura no identifica exclusivamente este juego")
    costs=[];unresolved=[];rounds=[];evidence_issues=[];snapshots=[];effective_modes=[];contexts={}
    def keep_issues(item):
        issues=item.get("issues",[])
        if not isinstance(issues,list) or not all(isinstance(x,str) for x in issues):raise ValueError("Problemas de evidencia malformados")
        if issues:
            unresolved.extend(issues)
            evidence_issues.append({k:deepcopy(item[k]) for k in ("ref","connection","game_code","issues") if k in item})
    observations=report.get("unresolved",[])
    warnings=report.get("warnings",[])
    if not isinstance(observations,list) or not isinstance(warnings,list) or not all(isinstance(x,str) for x in warnings):raise ValueError("Evidencia malformada")
    for item in observations:
        if not isinstance(item,dict):raise ValueError("Problema de evidencia malformado")
        keep_issues(item)
    unresolved.extend(warnings)
    configurations=report.get("configurations",[])
    if not isinstance(configurations,list) or not isinstance(report.get("rounds",[]),list):raise ValueError("Evidencia malformada")
    for configuration in configurations:
        if not isinstance(configuration,dict):raise ValueError("Configuración malformada")
        if configuration.get("game_code")!=symbol:raise ValueError("Configuración sin inicialización del mismo juego y conexión")
        keep_issues(configuration)
        parsed=configuration_domains(configuration.get("data"))
        contexts=parsed.get("contexts",{})
        effective_modes=parsed.get("effective_modes",[]) if not configuration.get("issues") and not parsed["unresolved"] else []
        snapshots.append({"source_ref":configuration.get("ref"),"contexts":deepcopy(contexts),"effective_modes":deepcopy(parsed.get("effective_modes",[])),"issues":list(configuration.get("issues",[]))+parsed["unresolved"]})
        for cost in parsed["costs"]:
            existing=next((item for item in costs if {k:v for k,v in item.items() if k not in ("source_ref","source_refs")}==cost),None)
            ref=configuration.get("ref")
            if existing is None:costs.append({**cost,"source_ref":ref,"source_refs":[ref]})
            elif ref not in existing["source_refs"]:existing["source_refs"].append(ref)
        unresolved.extend(parsed["unresolved"])
    for event in report.get("rounds",[]):
        if not isinstance(event,dict):raise ValueError("Ronda malformada")
        if event.get("game_code")!=symbol:raise ValueError("Ronda sin inicialización del mismo juego y conexión")
        keep_issues(event)
        if event.get("direction")=="received":rounds.append({"source_ref":event.get("ref"),**round_evidence(event)})
    if not configurations:unresolved.append("CONFIGURATION_NOT_OBSERVED")
    return {"costs":costs,"effective_modes":effective_modes,"contexts":contexts,"configuration_snapshots":snapshots,
            "observed_rounds":rounds,"unresolved":sorted(set(unresolved)),"evidence_issues":evidence_issues,
            "feature_domains":{k:{"declaration_state":"UNKNOWN","options":[]} for k in ("purchase","antebet")},
            "certifies_game_ok":False,"execution_pending":True}
