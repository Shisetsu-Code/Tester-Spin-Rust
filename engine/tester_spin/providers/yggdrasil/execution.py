"""Current-session Yggdrasil execution and shared return-to-base evidence."""
from __future__ import annotations
import json
import time
from tester_spin.models import SpinAttempt, utc_now_iso
from tester_spin.return_to_base import verify_return_to_base
from .runtime import DemoRuntime, Unsupported, RemoteFailure
from .protocol import mode_kind

def execute(provider, game, result, run_dir, *, spins, timeout_s, stop_event, progress):
    started = time.monotonic()
    runtime = DemoRuntime(provider.http, game.symbol, timeout_s, stop_event, gate=provider.request_gate,capture_path=run_dir/"analysis"/"http.har")
    try:
        config = runtime.bootstrap()
        if config["unresolved"]:
            from .sdk_mode_roles import load_source
            from .runtime import configuration
            page=provider.har_artifact_dir(game)/"official-page.html"
            if page.is_file():
                source=load_source(provider.http,page.read_text(encoding="utf-8"),game.symbol,config['wire_modes'],run_dir/"analysis",timeout_s)
                if source is not None:
                    config=configuration(runtime.bootstrap_data,game.symbol,runtime.currency,sdk_source=source)
                    runtime.config=config
                    progress("Yggdrasil: roles del cliente oficial contrastados con los modos y precios actuales.")
    except InterruptedError:
        result.status, result.error = "CANCELADO", 'Detención solicitada durante bootstrap Demo'
        return result
    except (Unsupported, ValueError, TypeError, AttributeError) as exc:
        result.error = 'Yggdrasil: configuración Demo no ejecutable: ' + str(exc)
        return result
    except RemoteFailure as exc:
        result.status, result.error = "ERROR", "Yggdrasil: " + str(exc)
        return result
    except Exception as exc:
        result.status, result.error = "ERROR", 'Yggdrasil: bootstrap Demo falló (' + type(exc).__name__ + ")"
        return result
    (run_dir / "current-server-configuration.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    modes = []
    for name in sorted(config["modes"], key=lambda value: (value != "BASIC", value)):
        mode_id = "SPIN" if name == "BASIC" else name
        kind = config["mode_kinds"][name]
        modes.append({"id":mode_id,"kind":kind,"wire_command": "" if name == "BASIC" else name,
            "declared":True,"server_declared":True,"source":"server.game.cfg.Modes", "role_source":config["role_source"], "evidence_level":"SERVER_ADVERTISED",
            "executable":name in config["templates"],"validated":False,"observed":False,
            "coverage_required":True,"required_options":[name],"covered_options":[],
            "required_samples":spins,"sample_counts":{name:0},"price_variants":config.get("purchase_variants",{}).get(name,{}),"request_shape":config["templates"].get(name,{}),
            "reason":config["unresolved"].get(name,"LIVE_EXECUTION_REQUIRED")})
    result.discovered_modes = modes
    result.samples_per_path = spins
    result.requested_spins = len(modes) * spins
    result.failed_spins = 0
    result.feature_domains["purchase"] = {"complete": not config["unresolved"], "source":config.get("purchase_role_source") or config["role_source"], "options":[k for k in config["modes"] if config["mode_kinds"][k]=="PURCHASE"]}
    result.feature_domains["ante"]={"complete":not config["unresolved"],"source":config["role_source"],"options":[k for k in config["modes"] if config["mode_kinds"][k]=="ANTE_BET"]}
    unresolved = [name + ": " + reason for name,reason in config["unresolved"].items()]
    continuation_commands=set()
    halt = False
    if "BASIC" not in config["templates"]:
        unresolved.append("Giro BASIC no reconstruible; no se ejecutan compras sin retorno verificable")
        halt = True
    for mode in modes:
        if halt:
            break
        name = mode["required_options"][0]
        template = config["templates"].get(name)
        if template is None:
            continue
        for sample in range(1,spins+1):
            if stop_event.is_set():
                result.status = "CANCELADO"
                unresolved.append('Detención solicitada')
                halt = True
                break
            directory = run_dir / mode["id"] / f"sample-{sample:03d}"
            attempt = SpinAttempt(number=len(result.attempts)+1,ok=False,mode_id=mode["id"],mode_kind=mode["kind"],symbol=game.symbol,artifact_dir=str(directory))
            tick = time.monotonic()
            try:
                selected=runtime.paid_template(name) if config.get("purchase_variants",{}).get(name) else template
                if selected is not template:
                    directory.mkdir(parents=True,exist_ok=True)
                    (directory/"current-purchase-price.json").write_text(json.dumps({"template":selected,"proof":runtime.purchase_price_proof},ensure_ascii=False,indent=2),encoding="utf-8")
                observed = runtime.round(selected,directory)
                continuation_commands.update(observed.get("continuation_commands",[]))
                mode["observed"] = True
                def probe_round(probe):

                    try:
                        returned = runtime.round(config["templates"]["BASIC"],probe)
                        continuation_commands.update(returned.get("continuation_commands",[]))
                        return returned
                    except Unsupported as exc:
                        return {"ok":True,"known":False,"base":False,"reason":str(exc)}
                proof = verify_return_to_base(directory, probe_round, stop_event=stop_event)
                attempt.ok = True
                attempt.status_code = 200
                attempt.wire_steps = observed["wire_steps"]
                attempt.terminal = proof["status"] == "CONFIRMED"
                if proof["status"] == "ERROR":
                    result.status = "ERROR"
                elif proof["status"] == "CANCELLED":
                    result.status = "CANCELADO"
                if not attempt.terminal:
                    reason = (proof.get("probes") or [{}])[-1].get("reason", "")
                    attempt.warning = "Retorno al giro normal: " + proof["status"] + (" (" + reason + ")" if reason else "")
                    unresolved.append(mode["id"] + ": " + attempt.warning)
                    halt = True
                else:
                    mode["sample_counts"][name] += 1
                    mode["execution_state"] = "PROVEN_TERMINAL"
                    mode["evidence_level"] = "REMOTE_EXECUTION"
            except InterruptedError:
                result.status = "CANCELADO"
                attempt.warning = 'Detención solicitada; ronda no acreditada'
                halt = True
            except (Unsupported, ValueError, TypeError, AttributeError) as exc:
                attempt.warning = str(exc)
                unresolved.append(mode["id"] + ": " + attempt.warning)
                halt = True
            except RemoteFailure as exc:
                result.status = "ERROR"
                attempt.error = str(exc) + '; petición no reintentada'
                unresolved.append(mode["id"] + ": " + attempt.error)
                halt = True
            except Exception as exc:
                result.status = "ERROR"
                attempt.error = 'Fallo de ejecución (' + type(exc).__name__ + '); no se reintenta la petición'
                unresolved.append(mode["id"] + ": " + attempt.error)
                halt = True
            attempt.elapsed_ms = (time.monotonic()-tick)*1000
            result.attempts.append(attempt)
            if attempt.ok and attempt.terminal:
                result.successful_spins += 1
            else:
                result.failed_spins += 1
            progress(f"{mode['id']} muestra {sample}/{spins}: " + ("cerrada y retorno confirmado" if attempt.terminal else attempt.warning or attempt.error))
            if halt:
                break
        if mode["sample_counts"][name] >= spins:
            mode.update(validated=True,covered_options=[name],reason="CLOSED_AND_RETURN_CONFIRMED",coverage_scope="server_paid_domain_with_resolved_zero_cost_controls/v1")
    for command in sorted(continuation_commands):
        modes.append({"id":command,"kind":"CONTINUATION","wire_command":command,"observed":True,"validated":True,"executable":True,"coverage_required":False,"evidence_level":"REMOTE_EXECUTION","execution_state":"PROVEN_TERMINAL"})
    if result.feature_domains["purchase"]["complete"]:
        # Replaces the old advertised-domain placeholder, not a game-specific path.
        # Coverage history keeps its evidence while the current server supplies
        # the actual required BB modes, each still subject to execution/return.
        modes.append({"id":"BUY_BONUS_UNRESOLVED","kind":"DIAGNOSTIC","executable":False,
            "coverage_required":False,"observed":True,"validated":False,
            "source":"server.game.cfg.Modes","reason":"CURRENT_PURCHASE_DOMAIN_RESOLVED"})
    result.failed_spins += max(0,result.requested_spins-len(result.attempts))
    if result.status not in {"ERROR","CANCELADO"}:
        result.status = "OK" if result.successful_spins == result.requested_spins and not unresolved else "PARCIAL"
    result.error = "; ".join(unresolved)
    result.finished_at = utc_now_iso()
    result.elapsed_ms = (time.monotonic()-started)*1000
    return result
