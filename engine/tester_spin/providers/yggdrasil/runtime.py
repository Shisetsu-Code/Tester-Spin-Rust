"""Yggdrasil Demo API 2.6.0: current declarations, paid rounds and collect."""
from __future__ import annotations
import json
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .protocol import COMMAND, PURCHASE, ANTE, mode_kind, command_values
from .limits import REQUEST_GATE
from .enum_choices import INDEX_COMMAND

SERVICE = "https://demo.yggdrasilgaming.com/game.web/service"

class Unsupported(ValueError):
    """Evidence does not authorize the next action; retain PARCIAL."""

class RemoteFailure(RuntimeError):
    """Transport or server rejection; never retry an uncertain paid request."""

def number(value):
    if isinstance(value, bool):
        raise ValueError('NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âºmero booleano')
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âºmero invÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡lido') from None
    if not value.is_finite():
        raise ValueError('NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âºmero no finito')
    return value

def decimal_text(value):
    return format(value.normalize(), "f")

def props_of(data):
    props = data.get("cfg", {}).get("props", [])
    result = {}
    for item in props:
        key = item.get("prop")
        if key in result:
            raise Unsupported('Propiedad de configuraciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n duplicada')
        value = item.get("value")
        if isinstance(value, str) and key in {"Modes", "Config"}:
            value = json.loads(value)
        result[key] = value
    return result

def denoms(value, currency):
    if not isinstance(value, str):
        raise Unsupported("Dominio de monedas ausente")
    groups = [part.split(":", 1)[1] for part in value.split(";") if part.startswith(currency + ":")]
    if len(groups) != 1:
        raise Unsupported('Moneda sin dominio inequÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­voco')
    values = [number(x) for x in groups[0].split(",")]
    if not values or any(x <= 0 for x in values):
        raise Unsupported('Dominio de monedas invÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡lido')
    return sorted(set(values))

def configuration(data, gameid, currency, *, sdk_source=None):
    identifiers = [str(data[k]) for k in ("gameid", "gameId") if k in data]
    if not identifiers or any(x != gameid for x in identifiers):
        raise Unsupported('ConfiguraciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n de otro juego')
    props = props_of(data)
    if "ApiVersion" in props and props["ApiVersion"] not in {"2.6.0","2.7.0","2.8.2"}:
        raise Unsupported('VersiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n API no demostrada')
    modes = props.get("Modes")
    if not isinstance(modes, dict) or "BASIC" not in modes or not all(isinstance(k, str) and COMMAND.fullmatch(k) and isinstance(v, dict) for k,v in modes.items()):
        raise Unsupported('Dominio Modes invÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡lido')
    if "ApiVersion" not in props:
        domain=props.get("CoinsPerBet")
        basic=(modes.get("BASIC") or {}).get("coinsPerBet")
        lines=props.get("Paylines")
        matches=(isinstance(domain,list) and bool(domain) and all(number(x)>0 for x in domain) and number(basic) in [number(x) for x in domain])
        if type(domain) in (int,float,str):matches=number(domain)>0 and number(domain)==number(basic)
        geometry=(domain is None and isinstance(lines,list) and bool(lines) and number(basic)==len(lines))
        fixed=False
        if domain is None:
            try:
                minimum=number(props.get('MinCoins'));maximum=number(props.get('MaxCoins'))
                fixed=(minimum>0 and minimum==minimum.to_integral_value() and minimum==maximum==number(basic))
            except ValueError:pass
        if not (matches or geometry or fixed):raise Unsupported("Classic coin domain does not match BASIC mode")
    declared_kinds={name:mode_kind(name) for name in modes}
    typed=(props.get("Config") or {}).get("bettingModes")
    typed_errors={}
    definition=(props.get('Config') or {}).get('definition')
    ante_multiplier=None
    if typed is None and isinstance(definition,dict) and 'ANTE_BET' in modes:
        try:
            candidate=number(definition.get('bonusBetMultiplier'))
            if candidate>1:
                ante_multiplier=candidate
                declared_kinds['ANTE_BET']='ANTE_BET'
        except ValueError:pass
    if typed is not None:
        if not isinstance(typed,list) or not typed:raise Unsupported("Typed betting modes must be a nonempty list")
        declared_kinds={name:"UNKNOWN_FEATURE" for name in modes}
        seen=set()
        for entry in typed:
            if not isinstance(entry,dict) or set(entry)!={"command","type","coinsPerBet"} or not isinstance(entry["command"],str):raise Unsupported("Malformed typed betting mode")
            name=entry["command"] or entry["type"]
            if name in seen or name not in modes:raise Unsupported("Duplicate or foreign typed betting mode")
            seen.add(name)
            kind={"BASIC":"SPIN","GOLDEN_BET":"ANTE_BET","BUY_BONUS":"PURCHASE"}.get(entry["type"],"UNKNOWN_FEATURE")
            if (name=="BASIC")!=(kind=="SPIN") or (kind=="SPIN" and entry["command"]!=""):raise Unsupported("Conflicting BASIC mode declaration")
            if number(entry["coinsPerBet"])!=number(modes[name].get("coinsPerBet")):
                typed_errors[name]="Typed coinsPerBet disagrees with Modes"
            else:declared_kinds[name]=kind
        for name in set(modes)-seen:typed_errors[name]="Mode missing from typed declaration"
    sdk_proof=None
    if sdk_source is not None:
        from .sdk_mode_roles import source_roles
        sdk_proof=source_roles(sdk_source,modes)
        if sdk_proof is not None:
            sdk_kinds={name:{"SPIN":"SPIN","ANTE_BET":"ANTE_BET","BUY_BONUS":"PURCHASE"}[role] for name,role in sdk_proof["roles"].items()}
            if typed is not None and (typed_errors or sdk_kinds!=declared_kinds):raise Unsupported("SDK and typed server mode roles disagree")
            if ante_multiplier is not None and sdk_kinds.get('ANTE_BET')!='ANTE_BET':raise Unsupported("SDK and server ante multiplier disagree")
            declared_kinds=sdk_kinds
    settings = [data.get("orgSettings") or {}] + list(data.get("extraOrgSettings") or [])
    if sdk_proof is not None and sdk_proof.get('purchase_price_factors'):
        domains={}
        for name in modes:
            records=[entry for entry in settings if isinstance(entry,dict) and entry.get('type')==name]
            if len(records)!=1:raise Unsupported("SDK purchase price domain is missing or ambiguous")
            record=records[0]
            try:
                quantity=number(modes[name]['coinsPerBet'])
                cash=[coin*quantity for coin in denoms(record.get('Denoms'),currency)]
                default=denoms(record.get('DefaultDenom'),currency)
                if len(default)!=1 or default[0] not in denoms(record.get('Denoms'),currency):raise ValueError()
                domains[name]=(cash,default[0]*quantity)
            except (ValueError,KeyError,TypeError):raise Unsupported("SDK purchase price domain is malformed") from None
        basic_cash,basic_default=domains['BASIC']
        for name,factor in sdk_proof['purchase_price_factors'].items():
            cash,default=domains[name]
            if cash!=[value*factor for value in basic_cash] or default!=basic_default*factor:
                raise Unsupported("SDK purchase price domain disagrees with current server settings")
    templates, unresolved = {}, {}
    paylines = (props.get("Config") or {}).get("Paylines")
    if paylines is None:paylines=props.get("Paylines")
    for mode, options in modes.items():
        if mode in typed_errors:
            unresolved[mode]=typed_errors[mode]
            continue
        if declared_kinds[mode]=="UNKNOWN_FEATURE":
            unresolved[mode] = "Modo anunciado sin primitiva de giro, compra o antebet"
            continue
        try:
            coins = number(options.get("coinsPerBet"))
            if coins <= 0 or coins != coins.to_integral_value():
                raise Unsupported('coinsPerBet invÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡lido')
            matching = [s for s in settings if isinstance(s, dict) and s.get("type") == mode]
            if len(matching) != 1:
                raise Unsupported('Falta configuraciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n de moneda por modo')
            allowed = denoms(matching[0].get("Denoms"), currency)
            coin = allowed[0]
            template = {"coin": decimal_text(coin), "coins": decimal_text(coins), "amount": decimal_text(coin * coins)}
            if paylines is not None:
                if not isinstance(paylines, list) or not paylines or not all(isinstance(line, list) and line for line in paylines):
                    raise Unsupported('Dominio de lÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­neas invÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡lido')
                template["lines"] = "1" * len(paylines)
            if mode != "BASIC":
                template["cmd"] = mode
            templates[mode] = template
        except (ValueError, TypeError, AttributeError) as exc:
            unresolved[mode] = str(exc)
    if ante_multiplier is not None and 'ANTE_BET' in templates:
        basic_template=templates.get('BASIC')
        if basic_template is None or number(templates['ANTE_BET']['amount'])!=number(basic_template['amount'])*ante_multiplier:
            templates.pop('ANTE_BET')
            unresolved['ANTE_BET']='Ante multiplier and current declared price disagree'
    constraints={"collection_modes":sorted(templates),"currency":currency,"basic_amount":templates.get("BASIC",{}).get("amount"),"basic_coin":templates.get("BASIC",{}).get("coin")}
    constraints['purchase_quotes']={name:templates[name] for name in templates if declared_kinds[name]=='PURCHASE'}
    from .growing_ways import declaration as growing_declaration
    growing_geometry=growing_declaration(props)
    if growing_geometry is not None:constraints['growing_ways_geometry']=growing_geometry
    from .seasonal_state import declaration as season_declaration
    season_roles=season_declaration(props)
    if season_roles is not None:constraints['season_reels']=season_roles
    from .direct_cup import declaration as cup_declaration
    cup_awards=cup_declaration(props)
    if cup_awards is not None:constraints['cup_coin_awards']=cup_awards
    from .saved_feature_neutral import declaration as saved_feature_declaration
    saved_geometry=saved_feature_declaration(props.get('Config'))
    if saved_geometry is not None:constraints['saved_feature_geometry']=saved_geometry
    from .collection_neutral import declaration as hunter_declaration
    hunter_definition=hunter_declaration(props.get('Config'))
    if hunter_definition is not None:constraints['hunter_definition']=hunter_definition
    from .edge_replacements import declaration as edge_declaration
    edge_definition=edge_declaration(props) or edge_declaration(props.get('Config'))
    if edge_definition is not None:constraints['edge_replacement']=edge_definition
    capacity=props.get('CollectionsCapacity')
    if isinstance(capacity,list) and 1<=len(capacity)<=20 and all(type(v) is int and 1<=v<=64 for v in capacity):constraints['collection_capacity']=capacity
    from .bbg_cascades import definition_contract
    if definition_contract(definition) is not None:constraints['bbg_definition']=definition
    if sdk_proof is not None:constraints['sdk_mode_profile']=sdk_proof['profile']
    if sdk_proof is not None and sdk_proof.get('award_command'):
        constraints['sdk_single_card_award_command']=sdk_proof['award_command']
    if sdk_proof is not None and sdk_proof.get('awarded_spin_menu'):
        constraints['sdk_awarded_spin_menu']=sdk_proof['awarded_spin_menu']
        constraints['sdk_card_quotes']={**templates,'BASE_SPIN':templates['BASIC']}
    from .portal_outcomes import declaration as portal_declaration
    portal_definition=portal_declaration(props.get('Config'))
    if portal_definition is not None:constraints['portal_definition']=portal_definition
    threshold=(props.get('Config') or {}).get('ExperienceToTriggerFreespins')
    if threshold is not None:
        try:
            value=number(threshold)
            if value>0:constraints['rage_trigger']=decimal_text(value)
        except ValueError:pass
    classic_lines=("ApiVersion" not in props and (props.get("CoinsPerBet") is None or type(props.get("CoinsPerBet")) in (int,float,str)) and isinstance(paylines,list) and bool(paylines) and number(modes["BASIC"].get("coinsPerBet"))==len(paylines))
    from .discounted_purchase import group_prices, SOURCE
    wire_modes=modes
    modes,purchase_variants,grouped=group_prices(modes,templates,unresolved)
    declared_kinds={name:kind for name,kind in declared_kinds.items() if name in modes}
    return {"wire_modes":wire_modes,"purchase_variants":purchase_variants,"purchase_role_source":SOURCE if grouped else None,"classic_line_quantity":classic_lines,"ordinary_constraints":constraints,"modes": modes, "mode_kinds":declared_kinds, "role_source":sdk_proof["profile"]+"+server.Modes" if sdk_proof is not None else "server.game.cfg.Config.bettingModes" if typed is not None else "server.game.cfg.Modes/Config.definition" if ante_multiplier is not None else "server.game.cfg.Modes", "templates": templates, "unresolved": unresolved, "api_version": props.get("ApiVersion"), "schema":"Modes/Denoms/coinsPerBet"}

def wager_state(payload):
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
        raise RemoteFailure("Respuesta rechazada por el servidor")
    data = payload.get("data")
    wager = data.get("wager") if isinstance(data, dict) else None
    if not isinstance(wager, dict) or not isinstance(wager.get("wagerid"), (str, int)) or isinstance(wager.get("wagerid"), bool) or not str(wager["wagerid"]):
        raise Unsupported("Respuesta sin ronda identificable")
    bets = wager.get("bets")
    if not isinstance(bets, list) or not bets or not all(isinstance(b,dict) and type(b.get("step")) is int and b["step"] > 0 for b in bets):
        raise Unsupported('Respuesta sin pasos vÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡lidos')
    steps = [b["step"] for b in bets]
    if len(set(steps)) != len(steps) or steps != sorted(steps):
        raise Unsupported("Pasos repetidos o desordenados")
    if any(b.get(field) is not None and not isinstance(b.get(field), dict) for b in bets for field in ("betdata", "eventdata")):
        raise Unsupported("Contenedor de comandos malformado")
    commands = []
    # SDKs getLastBet/getCurrentBet read the active step; earlier offers are history.
    for b in bets[-1:]:
        for part, field in ((b.get("betdata"), "cmds"), (b.get("eventdata"), "nextCmds")):
            if not isinstance(part, dict):
                continue
            values = part.get(field)
            if values in (None, "", [], {}):
                continue
            values = command_values(values)
            for value in values:
                if not isinstance(value, str) or not (COMMAND.fullmatch(value) or INDEX_COMMAND.fullmatch(value)):
                    if not (value=="*" and command_values((b.get("eventdata") or {}).get("nextCmds"))==["C","*"]):
                        value = "UNSUPPORTED_COMMAND"
                if value not in commands:
                    commands.append(value)
    terminal = wager.get("status") == "Finished" and all(b.get("status") == "RESULTED" for b in bets) and not commands
    return {"wagerid": str(wager["wagerid"]), "status": wager.get("status"), "bets": bets, "max_step": max(steps), "root_step": min(steps), "commands": commands, "terminal": terminal}

def classic_wildcard_collect(state):
    if state.get('commands')!=['C','*'] or not state.get('bets'):return False
    if command_values((state['bets'][-1].get('eventdata') or {}).get('nextCmds'))!=['C','*']:return False
    bd=state['bets'][0].get('betdata');keys={'lines','coin','nCoins','cheat','clientData'}
    if not isinstance(bd,dict) or set(bd) not in (keys,keys|{'initialBalance'}) or bd['cheat'] is not None or bd['clientData'] is not None:return False
    lines=bd['lines']
    if not isinstance(lines,str) or not 1<=len(lines)<=4096 or not set(lines)<={'0','1'} or '1' not in lines:return False
    try:return number(bd['coin'])>0 and number(bd['nCoins'])>0
    except ValueError:return False


def collect_request(state):
    if (state["commands"] != ["C"] and not classic_wildcard_collect(state)) or state["terminal"] or not all(b.get("status") == "RESULTED" for b in state["bets"]):
        raise Unsupported("Cobro C no autorizado por todos los pasos; comandos=" + ",".join(state["commands"]))
    return {"cmd": "C", "amount": "0", "wagerid": state["wagerid"], "step": str(state["max_step"] + 1), "betid": str(state["root_step"])}

def named_choice_command(state):
    commands=state["commands"]
    if not commands or "UNSUPPORTED_COMMAND" in commands or not all(isinstance(cmd,str) and COMMAND.fullmatch(cmd) for cmd in commands):return None
    event=state["bets"][-1].get("eventdata") or {}
    response=event.get("response") or {}
    cd=response.get("clientData") if isinstance(response,dict) else None
    actions=cd.get("actions") if isinstance(cd,dict) else None
    if not isinstance(actions,list):return None
    choices=[a for a in actions if isinstance(a,dict) and a.get("name")=="makeChoice"]
    if len(choices)!=1:return None
    choice=choices[0]
    if set(choice)!={"name","possibleChoices"}:return None
    available=choice["possibleChoices"]
    if not isinstance(available,list) or not 1<=len(available)<=256 or not all(isinstance(cmd,str) and COMMAND.fullmatch(cmd) for cmd in available) or len(set(available))!=len(available) or set(available)!=set(commands):return None
    if any(cmd=="GAMBLE" or cmd.startswith(("GAMBLE_","AG_","G_","GGB_")) for cmd in available):return None
    # Shared MakeChoiceRequest: raw command from the current menu, zero amount,
    # next step and root betid. No extra input is inferred from a label.
    return available[0]


def continuation_request(state,constraints=None):
    import re
    commands=state["commands"]
    from .supermeter import request as supermeter_request
    meter_request=supermeter_request(state)
    if meter_request is not None:return meter_request
    from .repeated_purchase_award import request as awarded_purchase_request
    awarded_request=awarded_purchase_request(state,constraints)
    if awarded_request is not None:return awarded_request
    from .side_award_choice import request as side_award_request
    side_request=side_award_request(state,constraints)
    if side_request is not None:return side_request
    from .gati_choices import collect_command,typed_menu_present
    gati_collect=collect_command(state)
    from .enum_choices import pick_command,menu_present
    enum_pick=pick_command(state)
    if menu_present(state) and enum_pick is None:raise Unsupported("Unlearned or malformed current numeric bonus choice")
    if typed_menu_present(state) and gati_collect is None:raise Unsupported("Malformed or mismatched current typed Gati choice domain")
    if (commands==["C"] or classic_wildcard_collect(state)) and gati_collect is None:return collect_request(state)
    exits=[];supported=False;paired=False
    profiles=[(r"NON_GAMBLE_[0-9]+",r"GAMBLE_[0-9]+_[0-9]+",True),(r"NO_GAMBLE",r"GAMBLE_[0-9]+",False),(r"NO_GAMBLE_[0-9]+",r"GAMBLE_[0-9]+",True),(r"NO_GAMBLE_[0-9]+",r"GAMBLE_[0-9]+_(?:LEFT|RIGHT)",False),(r"FREE_SPIN_(?:BASIC|GOLDEN_BET)_[0-9]+_PICKS",r"GAMBLE_(?:BASIC|GOLDEN_BET)_LVL_[0-9]+_POS_[0-9]+",False),(r"RG_[0-9]+",r"AG_[0-9]+_[0-9]+_[0-9]+",False),(r"NON_GAMBLE_(?:BASIC|GOLDEN)_[0-9]+_SCATTERS",r"GAMBLE_EGG_[0-9]+_(?:BASIC|GOLDEN)_[0-9]+_SCATTERS",False),(r"FREESPIN",r"GAMBLE",False),(r"Finished",r"Checkpoint",False)]
    for exit_pattern,risk_pattern,paired in profiles:
        exits=[cmd for cmd in commands if re.fullmatch(exit_pattern,cmd)]
        supported=all(re.fullmatch(exit_pattern,cmd) or re.fullmatch(risk_pattern,cmd) for cmd in commands)
        if supported and len(exits)==1:break
    if commands and len(commands)<=256 and any(all(re.fullmatch(pattern,cmd) for cmd in commands) for pattern in (r"PICK_BOX_[0-9]{2}",r"PICK_POSITION_[0-9]{1,3}")):
        exits=[commands[0]];supported=True;paired=False
    if not supported or len(exits)!=1:
        named=named_choice_command(state)
        if named is not None:exits=[named];supported=True;paired=False
    from .refusal_choices import no_risk_choice
    refusal=no_risk_choice(state)
    if refusal is not None:exits=[refusal["cmd"]];supported=True;paired=False
    from .card_award_choice import accept_command
    card_accept=accept_command(state,constraints)
    if card_accept is not None:exits=[card_accept];supported=True;paired=False
    from .parameter_choices import choice_parameters
    parameters=choice_parameters(state,constraints)
    if parameters is not None:exits=[commands[0]];supported=True;paired=False
    if gati_collect is not None and enum_pick is not None:raise Unsupported("Conflicting typed choice schemas")
    if gati_collect is not None:exits=[gati_collect];supported=True;paired=False
    if enum_pick is not None:exits=[enum_pick];supported=True;paired=False
    if state["terminal"] or not all(b.get("status")=="RESULTED" for b in state["bets"]) or not supported or len(exits)!=1:
        raise Unsupported("Unlearned or ambiguous continuation domain: "+",".join(commands))
    if paired and any(cmd.split("_")[1]!=exits[0].split("_")[-1] for cmd in commands if cmd.startswith("GAMBLE_")):
        count=int(exits[0].split("_")[-1])
        event=state["bets"][-1].get("eventdata") or {}
        response=event.get("response") or {}
        cd=response.get("clientData") if isinstance(response,dict) else None
        sequence=cd.get("clientDatas") if isinstance(cd,dict) else None
        awarded=sequence[-1] if isinstance(sequence,list) and sequence and isinstance(sequence[-1],dict) else {}
        # This SDK declares the awarded count and the next +2 gamble target.
        # It is distinct from the NON_GAMBLE group identity dialect.
        next_target=(exits[0].startswith("NO_GAMBLE_") and all(re.fullmatch(r"GAMBLE_[0-9]+",cmd) and int(cmd.split("_")[1])==count+2 for cmd in commands if cmd.startswith("GAMBLE_")) and type(awarded.get("freeSpinsAwarded")) is int and awarded["freeSpinsAwarded"]==count and awarded.get("freeSpinsWon") is True)
        if not next_target:raise Unsupported("Conflicting free-spin choice group")
    if exits[0].startswith("NO_GAMBLE_") and any(re.fullmatch(r"GAMBLE_[0-9]+_(?:LEFT|RIGHT)",cmd) for cmd in commands):
        if any(int(cmd.split("_")[1])!=int(exits[0].split("_")[-1])+1 for cmd in commands if cmd.startswith("GAMBLE_")):raise Unsupported("Conflicting side-gamble target level")
    if exits[0].startswith("RG_") and any(cmd.startswith("AG_") and cmd.split("_")[1]!=exits[0].split("_")[1] for cmd in commands):raise Unsupported("Conflicting gamble reward")
    if exits[0].startswith("FREE_SPIN_"):
        group=exits[0][len("FREE_SPIN_"):].rsplit("_",2)[0]
        if any(cmd.startswith("GAMBLE_") and cmd[len("GAMBLE_"):].split("_LVL_")[0]!=group for cmd in commands):raise Unsupported("Conflicting pick gamble mode")
    request={"cmd":exits[0],"amount":"0","wagerid":state["wagerid"],"step":str(state["max_step"]+1),"betid":str(state["root_step"])}
    if re.fullmatch(r"NON_GAMBLE_(?:BASIC|GOLDEN)_[0-9]+_SCATTERS",exits[0]):
        group=exits[0][len("NON_GAMBLE_"):]
        if any(cmd.startswith("GAMBLE_EGG_") and cmd.split("_",3)[-1]!=group for cmd in commands):raise Unsupported("Conflicting scatter gamble group")
        coin=number((state['bets'][0].get('betdata') or {}).get('coin'))
        if coin<=0:raise Unsupported('Choice coin is not declared by the current wager')
        request['coin']=decimal_text(coin)
    if parameters:request["clientParams"]=json.dumps(parameters,separators=(",",":"))
    if gati_collect is not None:request["clientParams"]=""
    if exits[0]=="FREESPIN":request["type"]="bonus"
    if exits[0]=="Finished":request["clientParams"]=json.dumps({"finishedByPlayer":True},separators=(",",":"))
    return request


def validate_transition(before, after, request,constraints=None):
    if before["wagerid"] != after["wagerid"] or after["max_step"] <= before["max_step"]:
        raise Unsupported("Identidad o avance de ronda inconsistente")
    if not any(b["step"] == int(request["step"]) and isinstance(b.get("betdata"), dict) and b["betdata"].get("cmd") == request["cmd"] for b in after["bets"]):
        raise Unsupported("Respuesta sin reconocimiento del cobro")
    currency=before["bets"][0].get("betcurrency")
    for generated in after["bets"]:
        if generated["step"] > before["max_step"]:
            if number(generated.get("betamount")) != 0 or generated.get("betcurrency") != currency:
                raise Unsupported("Continuation charged a new stake or changed currency")
    from .repeated_purchase_award import validate_transition as validate_purchased_transition
    try:validate_purchased_transition(before,after,request,constraints)
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError) as exc:raise Unsupported(str(exc)) from None
    from .supermeter import validate as validate_supermeter
    try:
        if validate_supermeter(before,after,request):return
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError) as exc:
        raise Unsupported("Accumulator transition rejected: "+str(exc)) from None
    prior = before["bets"][0].get("betdata") or {}
    collected = next(b["betdata"] for b in after["bets"] if b["step"] == int(request["step"]))
    if "cashBet" not in prior:
        from .classic_wire import collected_classic_bet
        if not collected_classic_bet(before,after,request):raise Unsupported("Classic collect changed wager or charged a new stake")
        return
    if any(number(collected.get(field)) != number(prior.get(field)) for field in ("coin", "cashBet")):
        raise Unsupported('El cobro cambiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³ el importe o moneda de la ronda')
    from .parameter_choices import validate_parameter_transition
    validate_parameter_transition(before,after,request,constraints)

def validate_start(state, template, currency="EUR", *, classic_line_quantity=False):
    root = state["bets"][0]
    bd = root.get("betdata")
    if root["step"] != 1 or not isinstance(bd, dict):
        raise Unsupported("Jugada no reconocida como ronda nueva")
    if root.get("betcurrency")!=currency or number(root.get("betamount"))!=number(template["amount"]):
        raise Unsupported("Paid wager currency or amount does not match request")
    for generated in state["bets"][1:]:
        if number(generated.get("betamount")) != 0 or generated.get("betcurrency") != currency:
            raise Unsupported("Automatic continuation charged an unrequested stake or changed currency")
    expected = template.get("cmd")
    if expected and bd.get("cmd") != expected:
        raise Unsupported("Compra no reconocida por el servidor")
    from .classic_wire import echoed_base_bet
    if not expected and bd.get("cmd") in (None,"") and echoed_base_bet(root,template,currency,classic_line_quantity):return
    if not expected and bd.get("cmd") not in {"BASE_SPIN", "BASE_GAME"}:
        raise Unsupported("Giro ordinario no reconocido por el servidor")
    if number(bd.get("cashBet")) != number(template["amount"]) or number(bd.get("coin")) != number(template["coin"]):
        raise Unsupported("Importe o moneda de respuesta distinto a la jugada")

def ordinary_round(state,constraints=None):
    if len(state["bets"]) != 1:
        return False
    from .random_multiplier_base import ordinary as ordinary_random_multiplier
    if ordinary_random_multiplier(state['bets'][0],constraints):return True
    from .growing_ways import ordinary as ordinary_growing_ways
    if ordinary_growing_ways(state['bets'][0],constraints):return True
    from .side_ledgers import ordinary as ordinary_side_ledgers
    if ordinary_side_ledgers(state['bets'][0],constraints):return True
    from .collection_neutral import ordinary as ordinary_hunter_neutral
    if ordinary_hunter_neutral(state['bets'][0],constraints):return True
    from .saved_feature_neutral import ordinary as ordinary_saved_feature
    if ordinary_saved_feature(state['bets'][0],constraints):return True
    from .respin_neutral import ordinary as ordinary_respin_neutral
    if ordinary_respin_neutral(state['bets'][0],constraints):return True
    from .supermeter import ordinary as ordinary_supermeter
    if ordinary_supermeter(state["bets"][0],constraints):return True
    from .classic_wire import ordinary_flat_event,ordinary_jackpot_collections
    from .base_game_state import ordinary_flat_multiplier
    event=state["bets"][0].get("eventdata")
    if isinstance(event,dict) and (event.get("freeSpins") or event.get("freeSpinTypePlayed")):return False
    from .collection_actions import ordinary_collection_actions,collection_envelope
    if collection_envelope(event):return ordinary_collection_actions(state["bets"][0],constraints)
    if isinstance(event,dict) and "response" not in event:
        return ordinary_flat_event(event,constraints) or ordinary_jackpot_collections(event) or ordinary_flat_multiplier(event)
    from .typed_actions import ordinary_typed_actions
    if ordinary_typed_actions(state["bets"][0]):return True
    cd = ((state["bets"][0].get("eventdata") or {}).get("response") or {}).get("clientData")
    if not isinstance(cd, dict):
        return False
    if {'gameStateAtSpinStart','gameStateAtSpinEnd','extraFreeSpins','extraWilds'}<=set(cd):
        from .portal_outcomes import ordinary as ordinary_portal
        return ordinary_portal(state['bets'][0],constraints)
    from .bbg_cascades import ordinary_dto,ordinary_cascade
    if ordinary_dto(cd):return ordinary_cascade(state["bets"][0],constraints)
    if set(cd)=={'Bet','Code','Completed','Round'} and (constraints or {}).get('sdk_mode_profile')=='sdk.dynamicModes/defaultBuy/excludedGolden/v1':
        from .round_outcomes import ordinary as ordinary_round_family
        return ordinary_round_family(state['bets'][0],constraints)
    from .client_data_sequence import ordinary_sequence
    if "clientDatas" in cd:return ordinary_sequence(cd)
    from .enum_outcomes import ordinary_enum_round
    from .gati_outcomes import ordinary_gati
    from .base_game_state import ordinary_neutral_board_multiplier
    if ordinary_neutral_board_multiplier(cd):return True
    from .base_game_state import ordinary_variable_heights,ordinary_no_award,ordinary_numeric_grid,ordinary_board_win,ordinary_multiplier_base,ordinary_numeric_bonus_flags,ordinary_multiplier_board,ordinary_board_metadata,ordinary_closed_flags
    if ordinary_variable_heights(cd) or ordinary_gati(cd) or ordinary_closed_flags(cd) or ordinary_board_metadata(cd) or ordinary_flat_multiplier(cd) or ordinary_multiplier_board(cd) or ordinary_enum_round(cd) or ordinary_numeric_bonus_flags(cd) or ordinary_multiplier_base(cd) or ordinary_board_win(cd) or ordinary_no_award(cd) or ordinary_numeric_grid(cd) or ordinary_flat_event(cd,constraints) or ordinary_jackpot_collections(cd):return True
    if "gameMode" in cd:
        from .base_game_state import ordinary_base_game
        return ordinary_base_game(cd)
    if cd.get("freeSpinTypePlayed") or cd.get("freeSpins"):
        return False
    if "actions" in cd and isinstance(cd["actions"],list) and cd["actions"] and all(isinstance(a,dict) and "name" in a for a in cd["actions"]):
        from .named_actions import ordinary_named_actions
        return ordinary_named_actions(cd)
    if "actions" in cd:
        actions = cd["actions"]
        if cd.get("isFinished") is not True or not isinstance(actions, list) or not actions or not all(isinstance(a,dict) and isinstance(a.get("$type"),str) for a in actions):
            return False
        from .balanced_features import ordinary_balanced_features
        return ordinary_balanced_features(cd)
    features = cd.get("featuresUsed")
    return set(cd)=={"featuresUsed"} and isinstance(features, list) and bool(features) and all(x == "noFeature" for x in features)

class DemoRuntime:
    def __init__(self, http, gameid, timeout_s, stop_event, *, gate=REQUEST_GATE, capture_path=None):
        self.http, self.gameid, self.timeout_s, self.stop_event = http, gameid, timeout_s, stop_event
        self.gate = gate
        from tester_spin.http_har import HTTPHar
        self.capture=HTTPHar(capture_path) if capture_path is not None else None
        self.currency = "EUR"
        self.token = ""
        self.seen_wagers = set()
        self.round_refs = {}

    def call(self, fn, body=None, query=None):
        if self.stop_event.is_set():
            raise InterruptedError('DetenciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n solicitada')
        if self.gate is not None:
            try:
                self.gate.acquire(self.stop_event, max_wait_s=self.timeout_s)
            except TimeoutError as exc:
                raise RemoteFailure(str(exc)+'; peticiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n no enviada') from None
        headers = {"GAME-ID": self.gameid, "Origin": "https://staticdemo.yggdrasilgaming.com", "Referer": "https://staticdemo.yggdrasilgaming.com/", "X-CRID": uuid.uuid4().hex}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        params = {"fn": fn, **(query or {})}
        sent=time.monotonic()
        if body is None:
            response = self.http.get(SERVICE, params=params, headers=headers, timeout=self.timeout_s)
        else:
            response = self.http.post(SERVICE, params=params, data=body, headers=headers, timeout=self.timeout_s)
        if self.capture is not None:
            self.capture.append(SERVICE,params,body,headers,response,time.monotonic()-sent)
        if response.status_code != 200:
            if response.status_code == 429 and self.gate is not None:
                try:self.gate.cooldown(getattr(response, "headers", {}).get("Retry-After"))
                except OSError:pass  # Memory cooldown survives; preserve the remote 429 diagnosis.
            raise RemoteFailure(f"HTTP {response.status_code} en {fn}; peticiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n no reintentada")
        try:
            value = response.json()
        except (ValueError, TypeError):
            raise RemoteFailure('Respuesta no JSON; peticiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n no reintentada') from None
        if not isinstance(value, dict) or type(value.get("code")) is not int or value["code"] != 0:
            code = value.get("code") if isinstance(value, dict) else None
            label = str(code) if type(code) is int else type(code).__name__
            raise RemoteFailure("Rechazo del servicio " + fn + " (code=" + label + ")")
        return value

    def bootstrap(self):
        auth = self.call("authenticate", {"org":"Demo", "gameid":self.gameid, "lang":"en", "currency":self.currency, "userName":"tester-"+uuid.uuid4().hex, "channel":"pc", "license":"mt"}, {"org":"Demo"})
        data = auth.get("data")
        if not isinstance(data, dict) or data.get("org") != "Demo" or data.get("currency") != self.currency or not isinstance(data.get("token"), str) or not data["token"]:
            raise Unsupported('AutenticaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n sin contrato Demo comprobado')
        self.token = data["token"]
        value = self.call("game", query={"org":"Demo", "gameid":self.gameid,"currency":self.currency})
        self.bootstrap_data=value.get("data", {})
        self.config = configuration(value.get("data", {}), self.gameid, self.currency)
        restored = self.call("restore")
        restore = restored.get("data")
        if not isinstance(restore, dict) or restore.get("empty") is not True:
            raise Unsupported('SesiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n nueva contiene estado restaurado o ambiguo')
        return self.config

    def paid_template(self, mode):
        from .discounted_purchase import selected_price
        variants=self.config.get("purchase_variants",{}).get(mode)
        if variants is None:return dict(self.config["templates"][mode])
        payload=self.call("info",query={"org":"Demo","currency":self.currency,"what":"playerState"})
        template,proof=selected_price(variants,payload,self.config["templates"][mode]["coin"])
        self.purchase_price_proof=proof
        return template

    def save(self, directory, index, request, state, choices=None, transition_validated=False):
        constraints=getattr(self,"config",{}).get("ordinary_constraints")
        directory.mkdir(parents=True, exist_ok=True)
        ref = self.round_refs.setdefault(state["wagerid"], "round-"+str(len(self.round_refs)+1))
        safe = {"round_ref":ref,"status":state["status"], "terminal":state["terminal"],"next_commands":state["commands"],"bets":[]}
        if classic_wildcard_collect(state):safe["continuation_markers"]={"*":"server_wildcard; not_an_executable_choice"}
        if choices is None and len(state["commands"])>1:
            try:
                offered=continuation_request(state,constraints)
                if offered["cmd"] not in {"C","Finished"}:choices={"available":state["commands"],"selected":None}
            except Unsupported:pass
        from .refusal_choices import no_risk_choice
        refusal=no_risk_choice(state)
        if refusal is not None:safe["refusal_menu"]={"step":state["max_step"],**refusal}
        from .parameter_choices import current_info
        parameter_menu=current_info(state,constraints)
        if parameter_menu is not None:
            safe['sdk_parameter_menu']={'step':state['max_step'],**parameter_menu,'options':{'playerChoice':{'-1':'KEEP_CURRENT_FREE_SPINS','1':'GAMBLE'}} if parameter_menu['command']=='Bonus' else {},'coverage_scope':'current_declared_award_and_safe_exit; not_all_gamble_results'}
        if request.get('cmd') in ('Bonus','FreeSpin'):
            try:parameters=json.loads(request.get('clientParams',''))
            except (ValueError,TypeError):parameters=None
            safe['sdk_parameter_request']={'command':request['cmd'],'parameters':parameters,'transition_validated':transition_validated}
            safe['parameterized_bonus_results']=[{'step':b['step'],'status':b.get('status'),'clientData':{k:v for k,v in (((b.get('eventdata')or{}).get('response')or{}).get('clientData')or{}).items() if k not in {'wagerId','wagerid','ResultId','ResultTime'}}} for b in state['bets'] if isinstance((((b.get('eventdata')or{}).get('response')or{}).get('clientData')),dict)]

        from .gati_choices import collect_command
        if collect_command(state) is not None:
            safe["gati_choice_options"]={"step":state["max_step"],"Gamble":state["bets"][-1]["eventdata"]["response"]["clientData"]["Gamble"]}
        from .enum_choices import pick_command,current_data
        if pick_command(state) is not None:
            safe["enum_bonus_choice"]={"step":state["max_step"],"NextRound":current_data(state)["NextRound"]}
        if choices is not None:
            safe["choices"]={**choices,"scope":"server_offered_current_step; not_all_branches_tested","protocol":"yggdrasil-current-zero-cost-menu/v1"}
        safe["transition_validated"]=transition_validated
        for bet in state["bets"]:
            bd = bet.get("betdata") or {}
            cd = ((bet.get("eventdata") or {}).get("response") or {}).get("clientData") or {}
            from .named_actions import ordinary_named_actions
            from .base_game_state import ordinary_base_game,ordinary_flat_multiplier
            from .balanced_features import ordinary_balanced_features
            from .base_game_state import ordinary_variable_heights,ordinary_no_award,ordinary_numeric_grid,ordinary_board_win,ordinary_multiplier_base,ordinary_numeric_bonus_flags,ordinary_multiplier_board,ordinary_board_metadata,ordinary_closed_flags
            from .classic_wire import ordinary_flat_event,ordinary_jackpot_collections
            from .enum_outcomes import ordinary_enum_round
            from .gati_outcomes import ordinary_gati
            from .collection_actions import ordinary_collection_actions,collection_envelope
            if ordinary_collection_actions(bet,constraints):
                safe.setdefault("ordinary_collection_outcomes",[]).append({"step":bet["step"],"schema":"current-stake-collection/v1","mode_domain":(constraints or {}).get("collection_modes"),"betdata":{"coin":bd["coin"],"cmd":bd["cmd"]},"eventdata":bet["eventdata"]})
            from .typed_actions import ordinary_typed_actions
            typed_base=ordinary_typed_actions(bet)
            from .bbg_cascades import ordinary_cascade
            bbg_base=ordinary_cascade(bet,constraints)
            if bbg_base:
                safe.setdefault('ordinary_bbg_cascade_outcomes',[]).append({'step':bet['step'],'schema':'bbg-base-server-definition-cash-cascades/v1','definition':(constraints or {}).get('bbg_definition'),'bet':{**{k:bet[k] for k in ('step','status','betamount','betcurrency','eventdata')},'betdata':{k:v for k,v in bd.items() if k!='initialBalance'}}})
            if typed_base:
                safe.setdefault("ordinary_typed_action_outcomes",[]).append({"step":bet["step"],"schema":"cash-normalized-base-actions/v1","bet":{**{k:bet[k] for k in ("step","status","betamount","betcurrency","eventdata")},"betdata":{k:v for k,v in bd.items() if k!="initialBalance"}}})
            from .client_data_sequence import ordinary_sequence,known_awarded_sequence
            from .growing_ways import ordinary as ordinary_growing_ways
            from .side_ledgers import ordinary as ordinary_side_ledgers
            explicit_base=(ordinary_side_ledgers(bet,constraints) or ordinary_growing_ways(bet,constraints) or typed_base or bbg_base or ordinary_variable_heights(cd) or ordinary_sequence(cd) or ordinary_collection_actions(bet,constraints) or ordinary_gati(cd) or ordinary_closed_flags(cd) or ordinary_board_metadata(cd) or ordinary_flat_multiplier(cd) or ordinary_multiplier_board(cd) or ordinary_enum_round(cd) or ordinary_base_game(cd) or ordinary_balanced_features(cd) or ordinary_numeric_bonus_flags(cd) or ordinary_multiplier_base(cd) or ordinary_board_win(cd) or ordinary_no_award(cd) or ordinary_numeric_grid(cd) or ordinary_flat_event(cd,constraints) or ordinary_jackpot_collections(cd)) if isinstance(cd,dict) else False
            named=(ordinary_collection_actions(bet,constraints) if collection_envelope(bet.get("eventdata")) else ordinary_named_actions(cd)) if isinstance(cd,dict) else False
            if isinstance(cd.get("actions"), list) and not named and not explicit_base:
                cd = dict(cd)
                cd["actions"] = [{k:a[k] for k in ("$type","modeName","featureIdentifier","name") if k in a} for a in cd["actions"] if isinstance(a,dict)]
            from .classic_wire import ordinary_flat_event,ordinary_jackpot_collections
            flat=bet.get("eventdata")
            if ordinary_flat_event(flat,constraints) or ordinary_jackpot_collections(flat) or ordinary_flat_multiplier(flat):
                safe.setdefault("ordinary_flat_outcomes",[]).append({"step":bet["step"],"schema":"classic-flat/v1" if ordinary_flat_event(flat,constraints) else "flat-multiplier/v1" if ordinary_flat_multiplier(flat) else "classic-jackpot/v1","data":flat})
            keep_cd=explicit_base or known_awarded_sequence(cd)
            safe["bets"].append({"step":bet["step"],"status":bet.get("status"),"command":bd.get("cmd"),"clientData":{k:v for k,v in cd.items() if k not in {"wagerId","wagerid","ResultId","ResultTime"}} if keep_cd else {k:cd[k] for k in ("featuresUsed","freeSpinTypePlayed","freeSpins","isFinished","actions")+( ("finalBoard",) if named else ()) if k in cd}})
        clean = {k:v for k,v in request.items() if k in {"cmd","amount","coin","coins","lines","step","betid","type","clientParams"}}
        (directory / f"step-{index:03d}-request.json").write_text(json.dumps(clean),encoding="utf-8")
        (directory / f"step-{index:03d}-response.json").write_text(json.dumps(safe),encoding="utf-8")

    def round(self, template, directory):
        body = {"channel":"pc","currency":self.currency,"lang":"en","gameid":self.gameid, **template}
        classic_lines=bool(getattr(self,"config",{}).get("classic_line_quantity")) and not template.get("cmd")
        if classic_lines:body.pop("coins",None)
        state = wager_state(self.call("play", body))
        validate_start(state,template,self.currency,classic_line_quantity=classic_lines)
        if state["wagerid"] in self.seen_wagers:
            raise Unsupported('El servidor reutilizÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³ una ronda anterior')
        self.seen_wagers.add(state["wagerid"])
        normal = not template.get("cmd") and ordinary_round(state,getattr(self,"config",{}).get("ordinary_constraints"))
        from .client_data_sequence import known_awarded_sequence
        from .parameter_choices import current_info
        root_cd=((state['bets'][0].get('eventdata') or {}).get('response') or {}).get('clientData')
        known_feature=bool(template.get('cmd')) or known_awarded_sequence(root_cd) or current_info(state,getattr(self,'config',{}).get('ordinary_constraints')) is not None
        self.save(directory,1,body,state)
        steps = 1
        continuation_commands=[]
        sequence_bets=list(state["bets"])
        while not state["terminal"]:
            if steps >= 32:
                raise Unsupported('LÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­mite de continuaciones; ronda sin cierre')
            request = continuation_request(state,getattr(self,"config",{}).get("ordinary_constraints"))
            following = wager_state(self.call("play", {"channel":"pc","currency":self.currency,"lang":"en","gameid":self.gameid, **request}))
            self.save(directory,steps+1,request,following,choices={"available":state["commands"],"selected":request["cmd"]} if len(state["commands"])>1 and request["cmd"]!="Finished" else None)
            validate_transition(state,following,request,getattr(self,"config",{}).get("ordinary_constraints"))
            self.save(directory,steps+1,request,following,choices={"available":state["commands"],"selected":request["cmd"]} if len(state["commands"])>1 and request["cmd"]!="Finished" else None,transition_validated=True)
            continuation_commands.append(request["cmd"])
            sequence_bets.extend(following["bets"])
            following["root_step"] = state["root_step"]
            state = following
            steps += 1
        from .free_board_sequence import known_sequence as known_free_board_sequence
        from .respin_sequence import known_sequence as known_respin_sequence
        from .walking_sequence import known_sequence
        board_sequence=known_free_board_sequence(sequence_bets,getattr(self,'config',{}).get('ordinary_constraints'))
        from .fight_sequence import known_sequence as known_fight_sequence
        fight_sequence=known_fight_sequence(sequence_bets,getattr(self,'config',{}).get('ordinary_constraints'))
        # A fully closed BASIC cascade remains a base round when no free-spin mode was awarded.
        if not template.get('cmd') and (fight_sequence or board_sequence and isinstance(root_cd,dict) and 'freeSpinsAwarded' not in root_cd):normal=True
        known_feature=known_feature or any(command!='C' for command in continuation_commands) or known_sequence(sequence_bets,getattr(self,'config',{}).get('ordinary_constraints')) or known_respin_sequence(sequence_bets,getattr(self,'config',{}).get('ordinary_constraints')) or board_sequence or fight_sequence
        known=bool(normal or known_feature)
        reason='CLOSED_ORDINARY_ROUND' if normal else 'CLOSED_FEATURE_ROUND' if known_feature else 'UNRECOGNIZED_CLOSED_OUTCOME'
        return {"ok":True,"known":known,"base":bool(normal),"terminal":True,"wire_steps":steps,"collected":"C" in continuation_commands,"continuation_commands":continuation_commands,"round_ref":self.round_refs[state["wagerid"]],"reason":reason}
