"""KA demo RMP execution grounded in the captured public client serializer."""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tester_spin.models import Game, GameTestResult, SpinAttempt, utc_now_iso
from tester_spin.providers.ka_gaming.limits import REQUEST_GATE
from tester_spin.providers.ka_gaming.cooldown import ServerCooldown, ServerRetryAfter


def load_signing_profile(root: Path) -> tuple[str, str, str] | None:
    # Keep the literal in local provider evidence, never in source or exports.
    files = sorted((root / "runtime").glob("game.min.*.js"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        source = path.read_text(encoding="utf-8")
        profile = parse_signing_profile(source)
        if profile:
            return profile
    return None


def parse_signing_profile(source: str):
    # Match the observed serializer algorithm, rather than build-specific
    # obfuscator names. Repeated context fields/hash functions must agree.
    identifier = r"[A-Za-z_$][A-Za-z0-9_$]*"
    signer = re.search(
        r'Cc\.' + identifier + r'=function\(a,b\)\{var d=Nb\.' + identifier
        + r'\(\),e=Ob\.(?P<hash>' + identifier + r')\(a\+"(?P<build>\d+)"\+b\.(?P<idv>' + identifier
        + r')\+d\),f=Ob\.(?P=hash)\(d\+b\.(?P=idv)\+b\.(?P<device>' + identifier
        + r')\),g=\$b\.Bb\(\)\.(?P<literal>' + identifier
        + r')\(\),e=Rb\(0==e%2\?d\+"(?P<version>[^"\n]+)"\+e\+g\+f\+a\+"(?P=build)":g\+a\+f\+b\.(?P=device)\+e\+"(?P=build)"\+d\);b\.'
        + identifier + r'=e\+d\}', source)
    if not signer:
        return None
    literal = re.search(re.escape(signer['literal']) + r':function\(\)\{return("(?:\\.|[^"\\])*")\}', source)
    if literal:
        return signer['build'], signer['version'], json.loads(literal.group(1))
    return None


def refresh_signing_profile(game, *, http, root, timeout_s, stop_event, progress):
    """Read the current official launcher and signer before each new session."""
    cooldown = ServerCooldown(root)
    def get(url):
        cooldown.check(stop_event)
        REQUEST_GATE.acquire(stop_event)
        cooldown.check(stop_event)
        response = http.get(url, headers={"Cache-Control": "no-cache"}, timeout=timeout_s)
        cooldown.observe(response.status_code, getattr(response, "headers", {}), url)
        cooldown.check(stop_event)
        if response.status_code == 404:
            progress("KA Gaming: HTTP 404 en este juego; se conserva el error y continúa el lote.")
        response.raise_for_status()
        return response.text
    if urlparse(game.url).hostname != "gamesdemo.kaga88.com":
        raise ValueError("KA Gaming: launcher no oficial")
    launcher = get(game.url)
    build = re.search(r"game\.min\.(\d+)\.js", launcher)
    if not build:
        raise ValueError("KA Gaming: el launcher no anuncia un cliente conocido")
    source = get("https://gamesdemo.kaga88.com/game.min." + build[1] + ".js")
    profile = parse_signing_profile(source)
    if profile is None or profile[0] != build[1]:
        raise ValueError("KA Gaming: firma actual no reconocida; no se envÃƒÂ­a apuesta")
    cache = root / "runtime"
    cache.mkdir(parents=True, exist_ok=True)
    temporary = cache / ("game.min." + build[1] + "." + secrets.token_hex(3) + ".tmp")
    temporary.write_text(source, encoding="utf-8")
    temporary.replace(cache / ("game.min." + build[1] + ".js"))
    progress("KA Gaming: cliente actual " + profile[1] + "; sesiÃƒÂ³n nueva por juego.")
    return profile


def client_hash(text: str) -> int:
    # JS charCodeAt hashes UTF-16 code units, including surrogate pairs.
    encoded = text.encode("utf-16-le", errors="surrogatepass")
    value = 0
    for index in range(0, len(encoded), 2):
        value = (31 * value + int.from_bytes(encoded[index:index + 2], "little")) & 0xFFFFFFFF
    return value if value < 0x80000000 else value - 0x100000000


def signed_context(raw: str, context: dict, profile: tuple[str, str, str], stamp: str) -> dict:
    build, version, literal = profile
    e = client_hash(raw + build + context["idv"] + stamp)
    f = client_hash(stamp + context["idv"] + context["dv"])
    material = (stamp + version + str(e) + literal + str(f) + raw + build
                if e % 2 == 0 else literal + raw + str(f) + context["dv"] + str(e) + build + stamp)
    return {**context, "ida": hashlib.sha256(material.encode()).hexdigest() + stamp}


def resolved_additional_spins(value) -> bool:
    """Accept the inline result shapes observed in ThreeMonkeys and AgentAngels."""
    if value is None or value == []:
        return True
    if not isinstance(value, list) or not value:
        return False
    fields = {"asi", "st", "swi", "snm", "ssm", "swm", "sw", "swu", "fsw", "sm", "tw"}
    screen_fields = {"asi", "st", "swm", "sw", "swu", "fsw", "tw"}
    ares_fields = screen_fields | {"sm"}
    def number(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
    for item in value:
        if not isinstance(item, dict) or set(item) not in (fields, screen_fields, ares_fields):
            return False
        if not isinstance(item["asi"], int) or isinstance(item["asi"], bool) or item["asi"] <= 0:
            return False
        arrays = ("st", "swi", "snm", "ssm", "sm") if set(item) == fields else ("st", "sm") if set(item) == ares_fields else ("st",)
        for field in arrays:
            if not isinstance(item[field], list) or not item[field] or not all(number(v) for v in item[field]):
                return False
        if not all(number(item[k]) for k in ("swm", "sw", "swu", "fsw", "tw")):
            return False
    return True


def base_terminal(state: dict) -> bool:
    # Only the observed resting state is accepted; unknown feature state stops.
    return (state.get("fs") is False and state.get("rf") == 0
            and state.get("acb") == 0 and resolved_additional_spins(state.get("as"))
            and not state.get("mb") and not state.get("fsr"))


def run_rmp_game(game: Game, *, http, root: Path, profile: tuple[str, str, str], modes: list[dict],
                 spins: int, timeout_s: float, stop_event: threading.Event, progress, capabilities=None) -> GameTestResult:
    started = utc_now_iso()
    clock = time.monotonic()
    run_dir = root / game.slug / "tests" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3))
    run_dir.mkdir(parents=True, exist_ok=True)
    attempts = []
    feature_domains = {}
    successes = 0
    error = ""
    status = "PARCIAL"
    endpoint = "https://rmpdemo.kaga88.com/kaga/command/spin"
    query = parse_qs(urlparse(game.url).query)
    if urlparse(game.url).hostname != "gamesdemo.kaga88.com" or query.get("p", [""])[0] != "demo":
        raise ValueError("KA RMP: sÃƒÆ’Ã‚Â³lo se admite el launcher oficial demo observado")
    user = str(secrets.randbelow(999_999_999) + 1)
    symbol = game.symbol or query.get("g", [""])[0]
    from tester_spin.providers.ka_gaming.device_context import current_client_identity
    agent,device=current_client_identity(getattr(http,'headers',{}).get('User-Agent'))
    context = {**device, "av": profile[1], "idv": secrets.token_hex(32),
               "lg": query.get("loc", ["es"])[0], "as": "", "ak": "accessKey"}
    from tester_spin.http_har import HTTPHar
    capture=HTTPHar(run_dir/"analysis"/"http.har")
    wire_index = 0
    session_http_rejected = False
    cooldown = ServerCooldown(root)
    retry_metadata = {}
    artifact_dir = run_dir

    def post(path: str, body: dict) -> dict:
        nonlocal wire_index, session_http_rejected
        cooldown.check(stop_event)
        REQUEST_GATE.acquire(stop_event)
        cooldown.check(stop_event)
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        ctx = signed_context(raw, context, profile, str(int(time.time() * 1000)))
        params = {"ak": "accessKey", "cr": "USD", "m": 0, "u": user}
        label = f"{wire_index:03d}-{path.rsplit('/', 1)[-1]}"
        wire_index += 1
        # Local evidence contains payloads; reusable contracts omit credentials.
        (artifact_dir / (label + ".request.json")).write_text(json.dumps({"method": "POST", "endpoint": "https://rmpdemo.kaga88.com/kaga/" + path,
            "params": {**params, "u": "<demo-user>"}, "payload": body}, ensure_ascii=False, indent=2), encoding="utf-8")
        endpoint_url="https://rmpdemo.kaga88.com/kaga/"+path
        headers={"User-Agent":agent,"Content-Type":"application/json","ctx":json.dumps(ctx,separators=(",",":")),
                 "Origin":"https://gamesdemo.kaga88.com","Referer":"https://gamesdemo.kaga88.com/"}
        sent=time.monotonic()
        response=http.post(endpoint_url,params=params,data=raw,headers=headers,timeout=timeout_s)
        capture.append(endpoint_url,params,raw,headers,response,time.monotonic()-sent)
        (artifact_dir / (label + ".response.raw.json")).write_text(response.text, encoding="utf-8")
        cooldown.observe(response.status_code, getattr(response, "headers", {}), endpoint_url)
        cooldown.check(stop_event)
        if response.status_code == 404:
            session_http_rejected = True
            progress("KA Gaming: HTTP 404 en este juego; se conserva el error y continúa el lote.")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("e") is not False or data.get("ec") != 0:
            code = data.get("ec") if isinstance(data, dict) else "invalid-envelope"
            raise ValueError(f"KA RMP {path}: ec={code}")
        return data

    try:
        if stop_event.is_set():
            error = "EjecuciÃƒÆ’Ã‚Â³n detenida antes del arranque"
        else:
            initial = post("rmp/startGame", {"un": user, "pn": "demo", "ak": "accessKey", "gn": symbol,
                "loc": context["lg"], "to": "123", "cr": "USD", "gm": 0, "tb": None, "mi": -1, "mc": 0})
            if not initial.get("un") or not initial.get("si"):
                raise ValueError("KA RMP: startGame no devolviÃƒÆ’Ã‚Â³ un/si")
            context.update(u=initial["un"], c=initial["si"])
            if capabilities is not None:
                from tester_spin.providers.ka_gaming.capabilities import client_declarations
                declaration = client_declarations(capabilities.get('common',''), capabilities.get('client',''), symbol, initial)
                feature_domains = declaration['domains']
                if feature_domains['purchase']['complete']:
                    modes = [m for m in modes if m.get('kind') != 'PURCHASE' and m.get('id') != 'BUY_BONUS_UNRESOLVED'] + declaration['modes']
                (run_dir/'feature-declaration.json').write_text(json.dumps(declaration,indent=2),encoding='utf-8')

            state = initial.get("sgr", {}).get("lsd", {})
            allowed_cps = initial.get("cup") or initial.get("sgr", {}).get("cps")
            if isinstance(allowed_cps, list) and allowed_cps:
                if state.get("cps") not in allowed_cps:
                    valid = [value for value in allowed_cps if isinstance(value, (int, float))
                             and not isinstance(value, bool) and value > 0]
                    if not valid:
                        raise ValueError("KA RMP: tabla de cps invÃƒÆ’Ã‚Â¡lida")
                    state = {**state, "cps": min(valid)}
            if not base_terminal(state):
                error = "KA RMP: estado inicial activo; continuaciÃƒÆ’Ã‚Â³n todavÃƒÆ’Ã‚Â­a no observada"
            else:
                base_fields={k:state.get(k) for k in ('sel','cps','atb','dn')}
                def check_base(directory):
                    from tester_spin.return_to_base import verify_return_to_base,save_exchange
                    def play(target):
                        nonlocal state,artifact_dir
                        previous_dir=artifact_dir
                        artifact_dir=target
                        captures=[]
                        had_feature=False
                        try:
                            fields=dict(base_fields)
                            for step in range(1,65):
                                if stop_event.is_set():raise InterruptedError('DetenciÃƒÂ³n solicitada')
                                if any(not isinstance(fields.get(k),(int,float)) or isinstance(fields[k],bool)
                                       or not math.isfinite(fields[k]) for k in ('sel','cps','atb','dn')):
                                    return dict(ok=False,base=False,known=False,captures=captures,reason='unknown base wager')
                                command={'gn':symbol,'sid':secrets.randbelow(2_147_483_647),**fields}
                                reply=post('command/spin',command)
                                captures.append(save_exchange(target,command,reply,step))
                                state=reply.get('md',{})
                                if not isinstance(state,dict) or any(state.get(k)!=v for k,v in fields.items()):
                                    return dict(ok=True,base=False,known=False,captures=captures,reason='changed wager')
                                if isinstance(state,dict) and base_terminal(state):
                                    same_wager=all(state.get(k)==v for k,v in base_fields.items())
                                    return dict(ok=True,base=not had_feature and same_wager,known=same_wager,captures=captures)
                                had_feature=True
                                if (not isinstance(state,dict) or state.get('rf')!=0
                                        or not resolved_additional_spins(state.get('as')) or state.get('mb')
                                        or not (state.get('acb')==1 or state.get('fs') is True)):
                                    return dict(ok=True,base=False,known=False,captures=captures,reason='unknown continuation')
                                fields={k:state.get(k) for k in base_fields}
                            return dict(ok=True,base=False,known=False,captures=captures,reason='continuation limit')
                        finally:artifact_dir=previous_dir
                    return verify_return_to_base(directory,play,stop_event=stop_event)
                spin_mode = next(m for m in modes if m["id"] == "SPIN")
                purchases = [m for m in modes if m.get("id") == "BUY_POS_1" and m.get("pos") == [1] and m.get("source") in {"manual-har", "client-declaration"}]
                jobs = [spin_mode] * max(1, spins) + [m for m in purchases for _ in range(max(1,spins))]
                for number, mode in enumerate(jobs, 1):
                    if stop_event.is_set():
                        error = "EjecuciÃƒÆ’Ã‚Â³n detenida"
                        break
                    for field in ("sel", "cps", "atb", "dn"):
                        if not isinstance(state.get(field), (int, float)) or isinstance(state[field], bool):
                            raise ValueError(f"KA RMP: falta parÃƒÆ’Ã‚Â¡metro de apuesta {field}")
                    body = {"gn": symbol, "sel": state["sel"], "sid": secrets.randbelow(2_147_483_647),
                            "cps": state["cps"], "atb": state["atb"], "dn": state["dn"]}
                    if mode in purchases:
                        body["pos"] = [1]
                    artifact_dir = run_dir / f"attempt-{number:03d}"
                    artifact_dir.mkdir()
                    tick = time.monotonic()
                    result = post("command/spin", body)
                    state = result.get("md", {})
                    wager_matches = isinstance(state,dict) and all(state.get(k)==body[k] for k in base_fields)
                    terminal = wager_matches and base_terminal(state)
                    purchase_started = wager_matches and (mode not in purchases or (isinstance(state, dict) and state.get("pos") == [1]
                        and state.get("acb") == 1 and isinstance(state.get("fsr"), int)
                        and not isinstance(state.get("fsr"), bool) and state["fsr"] > 0))
                    terminal = terminal and purchase_started
                    steps = 1
                    # Only the free-games family demonstrated by these captures.
                    while not terminal and purchase_started and steps < 64:
                        if stop_event.is_set():break
                        if not isinstance(state, dict) or state.get("rf") != 0 or not resolved_additional_spins(state.get("as")) or state.get("mb") or not (state.get("acb") == 1 or state.get("fs") is True):break
                        if any(not isinstance(state.get(k), (int,float)) or isinstance(state[k], bool) for k in ("sel","cps","atb","dn")):break
                        continuation = {"gn":symbol,"sel":state["sel"],"sid":secrets.randbelow(2_147_483_647),"cps":state["cps"],"atb":state["atb"],"dn":state["dn"]}
                        result = post("command/spin", continuation)
                        steps += 1
                        state = result.get("md", {})
                        wager_matches=isinstance(state,dict) and all(state.get(k)==continuation[k] for k in base_fields)
                        if not wager_matches:break
                        terminal = base_terminal(state)
                    round_terminal=terminal
                    if terminal:
                        terminal=check_base(artifact_dir).get('status')=='CONFIRMED'
                    mode.update(executable=True, observed=True, validated=terminal, source="live-rmp" if mode["id"]=="SPIN" else mode["source"],
                        evidence_level="REMOTE_EXECUTION",execution_state="PROVEN_TERMINAL" if terminal else "CONTINUATION_PENDING")
                    mode["required_options"] = ["spin" if mode["id"]=="SPIN" else "pos:1"]
                    mode["covered_options"] = list(mode["required_options"]) if terminal else []
                    attempts.append(SpinAttempt(number=number, mode_id=mode["id"], mode_kind=mode.get("kind","SPIN"), ok=terminal, status_code=200, endpoint=endpoint,
                        terminal=round_terminal, wire_steps=steps, symbol=symbol, elapsed_ms=(time.monotonic() - tick) * 1000,
                        artifact_dir=str(artifact_dir), warning="" if terminal else "ContinuaciÃƒÂ³n o regreso al base KA pendiente"))
                    successes += int(terminal)
                    progress(f"[{game.name}] KA RMP SPIN {number}/{spins}: {'OK' if terminal else 'PARCIAL'}, ec=0.")
                    if not terminal:
                        error = "KA RMP: regreso al giro base pendiente" if round_terminal else "KA RMP: bonus/free games activo; continuaciÃƒÂ³n todavÃƒÂ­a no observada"
                        break
                if successes == len(jobs) and all(m.get("validated") for m in purchases):
                    status = "OK"
    except Exception as exc:
        if isinstance(exc, ServerRetryAfter):
            retry_metadata = exc.metadata
        status = "ERROR" if not successes else "PARCIAL"
        error = f"{type(exc).__name__}: {exc}"
    finally:
        artifact_dir = run_dir
        if context.get("c") and not stop_event.is_set() and not session_http_rejected and not retry_metadata:
            try:
                post("rmp/endSession", {"es": "quit"})
            except Exception as exc:
                if isinstance(exc, ServerRetryAfter):
                    retry_metadata = exc.metadata
                    status = "PARCIAL" if successes else "ERROR"
                    error = str(exc)
                progress(f"[{game.name}] KA RMP: cierre de sesiÃƒÆ’Ã‚Â³n pendiente ({type(exc).__name__}).")

    for mode in modes:
        if mode["id"] == "SPIN":
            mode.update(executable=True, observed=bool(attempts), validated=bool(successes),
                source="live-rmp", endpoint=endpoint, transport="rmp-http", reason="" if successes else error)
    # Informational catalog features do not prove a selectable request branch.
    # Only required modes may downgrade an otherwise terminal base execution.
    if status == "OK" and any(mode["id"] != "SPIN" and mode.get("coverage_required", True)
                              and not mode.get("validated") for mode in modes):
        status = "PARCIAL"
        error = "KA RMP: spin base validado; modos anunciados sin contrato observado"
    if status == 'OK' and any(domain.get('complete') is False for domain in feature_domains.values()):
        status = 'PARCIAL'
        error = 'KA RMP: declaracion del cliente incompleta; disponibilidad pendiente'
    return GameTestResult(provider="ka_gaming", slug=game.slug, game_name=game.name, game_url=game.url,
        symbol=symbol, requested_spins=len(jobs) if 'jobs' in locals() else max(1,spins), successful_spins=successes,
        failed_spins=max(0,(len(jobs) if 'jobs' in locals() else max(1,spins))-successes), status=status, error=error, discovered_modes=modes,
        started_at=started, finished_at=utc_now_iso(), elapsed_ms=(time.monotonic() - clock) * 1000,
        run_dir=str(run_dir), attempts=attempts, feature_domains=feature_domains,
        structural_map={"server_retry_after": retry_metadata} if retry_metadata else {})
