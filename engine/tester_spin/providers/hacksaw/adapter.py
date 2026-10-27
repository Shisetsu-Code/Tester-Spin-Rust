from __future__ import annotations
import json
import copy
import hashlib
import re
import threading
import time
import uuid
from io import BytesIO
from pathlib import Path
from curl_cffi import requests
from PIL import Image
from tester_spin.models import Game, GameTestResult, SpinAttempt, utc_now_iso
from tester_spin.providers.base import ProviderAdapter
from tester_spin.providers.result_farm_contract import ProviderFarmSpec, build_result_farm_contract, validate_result_farm_contract
from .catalog import GAME_ID, CATALOG_URL, games_from_html, games_from_rows
from .ledger import RoundLedger, balance, validate_declaration
from .return_check import check_return
from .runtime import API, checked_response, discover_modes, terminal, minimum_round_seconds, client_feature_types

SPEC = ProviderFarmSpec(provider="hacksaw", protocol_family="hacksaw-casino-json",
    bootstrap_strategy="hacksaw-public-demo-authenticate", transport="http-json",
    terminal_contract={"type": "provider", "name": "hacksaw-completed-round", "round.status": "completed", "round.possibleActions": []},
    stable_metadata_keys=("client_version",), mode_option_keys=("custom_bet_data", "custom_bet_data_evidence", "monetary_contract", "buyBonus", "feature_multiplier", "request_shape", "root_mode_id", "choice_field"),
    runtime_outputs=("sessionUuid",), protocol_static={"verification_contract": "hacksaw/verified-runtime/v2", "endpoint": API + "/play/bet",
        "custom_bet_data": {"selector":"bets[].customData","source":"current_client_literal_publish_and_same_sdk_transport","purchase_context":"same_flag_menu_selector_mapping","price_override":"forbidden"},
        "purchase_selector": "bets[].buyBonus", "bet_amount": "bets[].betAmount",
        "confirmation_action": "win_presentation_complete", "confirmation_round_field": "roundId"})


class HacksawProvider(ProviderAdapter):
    key = "hacksaw"
    display_name = "Hacksaw Gaming"
    catalog_url = CATALOG_URL
    max_test_concurrency = 1

    def __init__(self, data_root: Path):
        self.provider_root = Path(data_root) / "providers" / self.key
        self.provider_root.mkdir(parents=True, exist_ok=True)
        self.http = requests.Session(impersonate="chrome")
        self.set_catalog_authority(False, "Snapshot público sin autoridad de eliminación")

    def game_dir(self, game):
        if game.provider != self.key or not GAME_ID.fullmatch(game.slug) or game.symbol != game.slug:
            raise ValueError("Hacksaw: ID inválido")
        path = self.provider_root / game.slug
        path.mkdir(parents=True, exist_ok=True)
        return path

    def catalog_record_invalid_reason(self, game):
        try:
            games_from_rows([{"id": game.symbol, "title": game.name, "url": game.url, "thumbnail": game.thumbnail_url}])
            if game.provider != self.key or game.slug != game.symbol:
                return "Hacksaw: ID de catálogo inválido"
        except ValueError:
            return "Hacksaw: fila inválida"
        return ""

    def _metadata(self, game):
        try:
            data = json.loads((self.game_dir(game) / "game.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, game, **fields):
        metadata = {**self._metadata(game), "provider": self.key, "slug": game.slug, "symbol": game.symbol,
                    "name": game.name, "public_url": game.url, **fields}
        (self.game_dir(game) / "game.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def _thumbnail(self, game):
        target = self.game_dir(game) / "thumbnail.jpg"
        if not game.thumbnail_url:
            return
        if not target.is_file():
            response = self.http.get(game.thumbnail_url, timeout=15)
            response.raise_for_status()
            if len(response.content) > 10_000_000:
                raise ValueError("Hacksaw: miniatura demasiado grande")
            with Image.open(BytesIO(response.content)) as image:
                image.verify()
            target.write_bytes(response.content)
        game.thumbnail_path = str(target)

    def crawl_catalog(self, *, stop_event: threading.Event, progress, max_pages=100, on_game=None):
        self.set_catalog_authority(False, "Catálogo público/snapshot sin paginación completa certificada")
        if stop_event.is_set():
            return []
        snapshot = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
        games = games_from_rows(snapshot["games"])
        try:
            response = self.http.get(CATALOG_URL, timeout=25)
            response.raise_for_status()
            live = games_from_html(response.text)
            # Never replace a full snapshot with a truncated/WAF catalog.
            merged = {game.symbol: game for game in games}
            merged.update({game.symbol: game for game in live})
            games = list(merged.values())
            (self.provider_root / "catalog.html").write_text(response.text, encoding="utf-8")
        except Exception as exc:
            progress(f"Hacksaw: catálogo guardado ({type(exc).__name__}).")
        found = []
        for game in games:
            if stop_event.is_set():
                break
            try:
                self._thumbnail(game)
            except Exception:
                pass
            self._save(game, thumbnail_url=game.thumbnail_url, thumbnail_path=game.thumbnail_path)
            found.append(game)
            if on_game:
                on_game(game)
        progress(f"Hacksaw: {len(found)} juegos; demos sin recorrido masivo.")
        return sorted(found, key=lambda game: game.name.casefold())

    def har_artifact_dir(self, game):
        path = self.game_dir(game) / "analysis"
        path.mkdir(exist_ok=True)
        return path

    def farm_contract_dir(self, game):
        return self.game_dir(game)

    def test_game(self, game, *, spins, timeout_s, stop_event, progress):
        root = self.game_dir(game)
        requested = max(1, int(spins))
        result = GameTestResult(self.key, game.slug, game.name, game.url, requested, 0, requested, "PARCIAL", symbol=game.symbol)
        cached = self._metadata(game).get("discovered_modes")
        result.discovered_modes = cached if isinstance(cached, list) and cached else discover_modes({})
        if stop_event.is_set():
            result.error = "Ejecución detenida"
            return result
        start = time.monotonic()
        directory = root / "tests" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
        directory.mkdir(parents=True)
        result.run_dir = str(directory)
        try:
            version_response = self.http.get("https://static-live.hacksawgaming.com/" + game.symbol + "/version.json", timeout=timeout_s)
            version_response.raise_for_status()
            version = str(version_response.json().get("version") or "")
            if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
                raise ValueError("Hacksaw: versión de cliente desconocida")
            self._save(game, client_version=version)
            body = {"seq": 1, "partner": "demo", "gameId": game.symbol, "gameVersion": version,
                    "currency": "EUR", "languageCode": "en", "mode": 2, "branding": "default",
                    "channel": 1, "userAgent": "Mozilla/5.0", "token": "123131"}
            (directory / "authenticate.request.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
            response = self.http.post(API + "/play/authenticate", json=body, timeout=timeout_s,
                headers={"Origin": "https://static-live.hacksawgaming.com", "Content-Type": "application/json"})
            (directory / "authenticate.response.raw.json").write_text(response.text, encoding="utf-8")
            data = checked_response(response)
            validate_declaration(data)
            account_balance = balance(data, "EUR")
            client_source=''
            custom_profile=None
            try:
                client_response = self.http.get('https://static-live.hacksawgaming.com/'+game.symbol+'/'+version+'/main.js', timeout=timeout_s)
                client_response.raise_for_status()
                client_source=client_response.text
                types = client_feature_types(client_source)
            except Exception:
                types = {}
            data = {**data, 'client_feature_types':types, 'client_types_complete': bool(types)}
            (directory / 'feature-types.json').write_text(json.dumps(types, indent=2), encoding='utf-8')
            result.discovered_modes = discover_modes(data)
            from tester_spin.feature_domains import initialization_domains
            result.feature_domains = initialization_domains("hacksaw", data, result.discovered_modes)
            if not all(result.feature_domains.get(k, {}).get("complete") for k in ("purchase", "feature_spin")):
                result.error = "Hacksaw: declaración de opciones sin clasificación completa"
                return result
            if 'updateCustomBetData' in client_source:
                from .custom_bet_data import client_custom_bet_data
                sdk=self.http.get('https://static-live.hacksawgaming.com/'+game.symbol+'/'+version+'/casino/hacksaw-casino.min.js',timeout=timeout_s)
                sdk.raise_for_status()
                custom_profile=client_custom_bet_data(client_source,sdk.text)
                (directory/'custom-bet-data.json').write_text(json.dumps(custom_profile,indent=2),encoding='utf-8')
                if not custom_profile.get('proven') or not isinstance(custom_profile.get('default'),dict):
                    result.error='Hacksaw: datos adicionales de apuesta sin contrato de cliente y SDK'
                    return result
                evidence={'client_sha256':hashlib.sha256(client_source.encode('utf-8')).hexdigest(),
                    'sdk_sha256':hashlib.sha256(sdk.text.encode('utf-8')).hexdigest()}
                for mode in result.discovered_modes:
                    value=(custom_profile['default'] if mode['kind']=='SPIN' else custom_profile.get('by_selector',{}).get(str(mode.get('buyBonus'))))
                    if value is None:
                        result.error='Hacksaw: contexto adicional de compra sin selector contrastado'
                        return result
                    mode['custom_bet_data']=copy.deepcopy(value)
                    mode['custom_bet_data_evidence']=dict(evidence)
                    if isinstance(mode.get('request_shape'),dict):mode['request_shape']['bets'][0]['customData']=copy.deepcopy(value)
            levels = data.get("betLevels")
            session = data.get("sessionUuid")
            if (not isinstance(session, str) or not session or not isinstance(levels, list)
                    or not levels or not re.fullmatch(r"[1-9][0-9]*", str(levels[0]))
                    or data.get("roundStatus") not in (None, "completed")):
                result.error = "Hacksaw: perfil de apuesta o ronda inicial pendiente de captura"
                return result
            bet_amount = str(levels[0])
            for mode in result.discovered_modes:
                mode["executable"] = mode["kind"] != "UNKNOWN_FEATURE"
                if mode["id"] == "SPIN":
                    mode["required_options"] = ["spin"]
                mode["sample_counts"] = {}
            jobs = [result.discovered_modes[0]] * requested + [m for m in result.discovered_modes[1:] if m["executable"]]
            seq = 1
            confirmation_mode = None
            choice_modes = {}
            extra_choice_rounds = {}
            for mode in jobs:
                if stop_event.is_set():
                    result.error = "Ejecución detenida"
                    break
                attempt_dir = directory / f"attempt-{len(result.attempts) + 1:03d}"
                attempt_dir.mkdir()
                steps = 0
                attempt = SpinAttempt(number=len(result.attempts)+1, ok=False, mode_id=mode["id"],
                    mode_kind=mode["kind"], symbol=game.symbol, endpoint=API + "/play/bet", artifact_dir=str(attempt_dir))
                result.attempts.append(attempt)
                def post_bet(payload):
                    nonlocal steps, account_balance
                    steps += 1
                    (attempt_dir / f"{steps:03d}.request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
                    answer = self.http.post(API + "/play/bet", json=payload, timeout=timeout_s,
                        headers={"Origin": "https://static-live.hacksawgaming.com", "Content-Type": "application/json"})
                    (attempt_dir / f"{steps:03d}.response.raw.json").write_text(answer.text, encoding="utf-8")
                    attempt.wire_steps = steps
                    reply = checked_response(answer)
                    ledger.accept(reply)
                    account_balance = ledger.after
                    (attempt_dir / "ledger.json").write_text(json.dumps(ledger.proof(), indent=2), encoding="utf-8")
                    return reply
                bet = {"betAmount": bet_amount}
                if mode["kind"] in {"PURCHASE", "FEATURE_SPIN"}:
                    bet["buyBonus"] = mode["buyBonus"]
                if custom_profile is not None:bet['customData']=copy.deepcopy(mode['custom_bet_data'])
                ledger = RoundLedger(account_balance, "EUR", bet_amount,
                    mode.get("feature_multiplier") if mode["kind"] in {"PURCHASE", "FEATURE_SPIN"} else 1)
                seq += 1
                round_started = time.monotonic()
                answer = post_bet({"seq": seq, "sessionUuid": session, "bets": [bet],
                    "offerId": None, "promotionId": None, "autoplay": False})
                round_data = answer.get("round", {})
                first_choice = None
                choice_mode = None
                for decision_step in range(8):
                    actions = round_data.get("possibleActions")
                    if round_data.get("status") != "started" or not isinstance(actions, list) or not actions:
                        break
                    # possibleActions is the current server menu. The shared
                    # scalar continuation envelope is independent of option names.
                    # Do not interpret these selectors as paid bonus declarations.
                    if (len(actions) > 16 or any(not isinstance(action, str)
                            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", action)
                            or action == "win_presentation_complete" for action in actions)
                            or len(set(actions)) != len(actions)
                            or not isinstance(round_data.get("roundId"), str)
                            or not round_data["roundId"]):
                        break
                    family = actions
                    if stop_event.is_set():
                        result.error = "Ejecución detenida"
                        break
                    if first_choice is None:
                        choice_mode = choice_modes.get(mode["id"])
                        if choice_mode is None:
                            choice_mode = {"id": "CHOICE_" + mode["id"], "kind": "CHOICE_CONTINUATION",
                                "wire_command": "bet", "root_mode_id": mode["id"], "choice_field": "continueInstructions.action",
                                "executable": True, "validated": False, "coverage_required": True,
                                "required_options": [], "covered_options": [], "sample_counts": {},
                                "request_shape": {"continueInstructions": {"action": "<selected:action>"}}}
                            choice_modes[mode["id"]] = choice_mode
                            result.discovered_modes.append(choice_mode)
                        remaining_choices = [a for a in family if a in actions and a not in choice_mode["covered_options"]]
                        selected = remaining_choices[0] if remaining_choices else next(a for a in family if a in actions)
                        first_choice = selected
                    else:
                        # A single gamble probe may leave another decision. Finish
                        # via the advertised play action, never gamble repeatedly.
                        if "play" not in actions:
                            break
                        selected = "play"
                    for action in actions:
                        if action not in choice_mode["required_options"]:
                            choice_mode["required_options"].append(action)
                    round_id = round_data["roundId"]
                    seq += 1
                    answer = post_bet({"seq": seq, "sessionUuid": session, "roundId": round_id,
                        "continueInstructions": {"action": selected}})
                    round_data = answer.get("round", {})
                    if round_data.get("roundId") != round_id:
                        raise ValueError("Hacksaw: elección cambió de ronda")
                if round_data.get("status") == "wfwpc" and round_data.get("possibleActions") == [] and round_data.get("roundId"):
                    round_id = round_data["roundId"]
                    if confirmation_mode is None:
                        confirmation_mode = {"id": "CONFIRM_WIN", "kind": "CONTINUATION", "wire_command": "bet",
                            "executable": True, "validated": False, "coverage_required": True,
                            "required_options": ["win_presentation_complete"], "covered_options": [], "sample_counts": {},
                            "request_shape": {"continueInstructions": {"action": "win_presentation_complete"}}}
                        result.discovered_modes.append(confirmation_mode)
                    minimum = minimum_round_seconds(data.get("minimumRoundDuration"))
                    remaining = max(0.0, minimum - (time.monotonic() - round_started))
                    if remaining > timeout_s or stop_event.wait(remaining):
                        result.error = "Hacksaw: confirmación pendiente o ejecución detenida"
                        break
                    seq += 1
                    answer = post_bet({"seq": seq, "sessionUuid": session, "roundId": round_id,
                        "continueInstructions": {"action": "win_presentation_complete"}})
                    if answer.get("round", {}).get("roundId") != round_id:
                        raise ValueError("Hacksaw: confirmación cambió de ronda")
                    if terminal(answer):
                        confirmation_mode.update(observed=True, validated=True, evidence_level="REMOTE_EXECUTION", execution_state="PROVEN_TERMINAL")
                        confirmation_mode["covered_options"] = ["win_presentation_complete"]
                        counts = confirmation_mode["sample_counts"]
                        counts["win_presentation_complete"] = counts.get("win_presentation_complete", 0) + 1
                complete = terminal(answer) and ledger.closed
                attempt.ok = attempt.terminal = complete
                attempt.status_code = 200
                mode.update(observed=True, validated=complete, evidence_level="REMOTE_EXECUTION",
                    execution_state="PROVEN_TERMINAL" if complete else "CONTINUATION_PENDING")
                if complete:
                    mode["monetary_contract"] = "hacksaw/round-ledger/v1"
                    if choice_mode is not None:
                        if first_choice not in choice_mode["covered_options"]:
                            choice_mode["covered_options"].append(first_choice)
                        counts = choice_mode["sample_counts"]
                        counts[first_choice] = counts.get(first_choice, 0) + 1
                        covered = set(choice_mode["required_options"]).issubset(choice_mode["covered_options"])
                        choice_mode.update(observed=True, validated=covered, evidence_level="REMOTE_EXECUTION",
                            execution_state="PROVEN_TERMINAL" if covered else "CONTINUATION_PENDING")
                        if not covered:
                            extra = extra_choice_rounds.get(mode["id"], 0)
                            if extra < 2:
                                extra_choice_rounds[mode["id"]] = extra + 1
                                jobs.append(mode)
                            else:
                                result.error = "Hacksaw: elecciones pendientes tras agotar el límite de pruebas"
                    option = "spin" if mode["id"] == "SPIN" else str(mode["buyBonus"])
                    mode["covered_options"] = [option]
                    mode["sample_counts"][option] = mode["sample_counts"].get(option, 0) + 1
                    result.successful_spins = min(requested, result.successful_spins + int(mode["id"] == "SPIN"))
                progress(f"Hacksaw {game.name}: {mode['id']} {'OK' if complete else 'PARCIAL'}.")
                if not complete:
                    result.error = "Hacksaw: continuación desconocida pendiente de captura"
                    break
            if result.successful_spins == requested and all(mode.get("validated") for mode in result.discovered_modes):
                def return_send(payload):
                    nonlocal seq
                    seq += 1
                    request = copy.deepcopy({**payload, "seq": seq, "sessionUuid": session})
                    if custom_profile is not None:
                        for bet in request.get('bets',[]):bet['customData']=copy.deepcopy(custom_profile['default'])
                    answer = self.http.post(API + "/play/bet", json=request, timeout=timeout_s,
                        headers={"Origin": "https://static-live.hacksawgaming.com", "Content-Type": "application/json"})
                    return checked_response(answer)
                proof = check_return(return_send, directory, before=account_balance, stake=bet_amount,
                    currency="EUR", stop_event=stop_event, minimum_duration=data.get("minimumRoundDuration"), previous_round_id=ledger.round_id)
                result.structural_map["hacksaw_return"] = {"status": proof["status"],
                    "consecutive_base": proof["consecutive_base"], "schema": "hacksaw/verified-runtime/v2"}
                if proof["status"] == "CONFIRMED":
                    result.status = "OK"
                else:
                    result.error = "Hacksaw: retorno al giro normal no demostrado: " + proof["status"]
        except Exception as exc:
            result.status = "PARCIAL" if result.successful_spins else "ERROR"
            result.error = f"Hacksaw: {type(exc).__name__}: {exc}"
        finally:
            result.failed_spins = max(0, requested-result.successful_spins)
            result.finished_at = utc_now_iso()
            result.elapsed_ms = (time.monotonic() - start) * 1000
            self._save(game, discovered_modes=result.discovered_modes)
        progress(result.error)
        return result

    def build_farm_contract(self, game, result):
        contract = build_result_farm_contract(game, result, self.game_dir(game), SPEC)
        proof = result.structural_map.get("hacksaw_return", {})
        roots = [m for m in result.discovered_modes if m.get("kind") in {"SPIN", "PURCHASE", "FEATURE_SPIN"}]
        if (proof.get("schema") != "hacksaw/verified-runtime/v2" or proof.get("status") != "CONFIRMED"
                or proof.get("consecutive_base", 0) < 2 or not roots
                or any(m.get("monetary_contract") != "hacksaw/round-ledger/v1" for m in roots)):
            contract["ready"] = False
            contract["unresolved"].append("HACKSAW_CURRENT_MONEY_AND_RETURN_PROOF_REQUIRED")
        return contract

    def validate_farm_contract(self, contract):
        errors = validate_result_farm_contract(contract, SPEC)
        static = (contract.get("protocol") or {}).get("static") or {}
        if static.get("verification_contract") != "hacksaw/verified-runtime/v2":
            errors.append("HACKSAW_CURRENT_VERIFICATION_REQUIRED")
        for mode in contract.get("modes", []):
            if mode.get("kind") in {"SPIN", "PURCHASE", "FEATURE_SPIN"} and (mode.get("options") or {}).get("monetary_contract") != "hacksaw/round-ledger/v1":
                errors.append("HACKSAW_CURRENT_MONEY_PROOF_REQUIRED")
                break
        for mode in contract.get('modes',[]):
            options=mode.get('options') or {}
            if options.get('custom_bet_data'):
                if ((contract.get('protocol') or {}).get('static') or {}).get('custom_bet_data')!=SPEC.protocol_static['custom_bet_data']:
                    errors.append('HACKSAW_CUSTOM_BET_DATA_REQUIRED')
                evidence=options.get('custom_bet_data_evidence') or {}
                if not all(isinstance(evidence.get(k),str) and re.fullmatch('[0-9a-f]{64}',evidence[k]) for k in ('client_sha256','sdk_sha256')):
                    errors.append('HACKSAW_CUSTOM_BET_DATA_EVIDENCE_REQUIRED')
        return list(dict.fromkeys(errors))
