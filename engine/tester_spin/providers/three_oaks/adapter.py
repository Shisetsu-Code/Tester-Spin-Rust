from __future__ import annotations

import json
import hashlib
import threading
import time
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests
from PIL import Image

from tester_spin.models import Game, GameTestResult, SpinAttempt, utc_now_iso
from tester_spin.providers.base import ProviderAdapter
from tester_spin.providers.result_farm_contract import ProviderFarmSpec, build_result_farm_contract, validate_result_farm_contract
from .catalog import CATALOG_API, ORIGIN, SLUG, client_family, family_map, games_from_page, launcher_config
from .runtime import DemoSession, base_terminal, discover_modes, play_fields, affordable_purchase_fields, continuation_fields, source_continuation_rules

_SPEC = ProviderFarmSpec(provider="3oaks", protocol_family="three-oaks-goreel-commands",
    bootstrap_strategy="three-oaks-public-demo-login-start", transport="http-json-text-plain",
    terminal_contract={"type": "provider", "name": "three-oaks-completed-base-round",
        "round_finished": True, "current": "spins", "available_action": "spin"},
    stable_metadata_keys=("family", "vendor", "runtime_transport"),
    mode_option_keys=("selected_mode", "feature_multiplier", "family", "wire_action"),
    runtime_outputs=("demo_endpoint", "session_id"),
    protocol_static={"command": "play", "base_action": "spin", "purchase_action": "buy_spin"})


class ThreeOaksProvider(ProviderAdapter):
    key = "3oaks"
    display_name = "3 Oaks Gaming"
    catalog_url = ORIGIN + "/games"
    max_test_concurrency = 1
    min_catalog_reconcile_ratio = 0.8

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        self.provider_root = self.data_root / "providers" / self.key
        self.provider_root.mkdir(parents=True, exist_ok=True)
        self.http = requests.Session(impersonate="chrome")

    def game_dir(self, game: Game) -> Path:
        if not SLUG.fullmatch(game.slug):
            raise ValueError("3 Oaks: slug inválido")
        path = self.provider_root / game.slug
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _metadata(self, game: Game) -> dict:
        try:
            data = json.loads((self.game_dir(game) / "game.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            return {}

    def _save_metadata(self, game: Game, **fields):
        data = {**self._metadata(game), "provider": self.key, "slug": game.slug,
                "name": game.name, "public_url": game.url, "symbol": game.symbol, **fields}
        (self.game_dir(game) / "game.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def catalog_record_invalid_reason(self, game: Game) -> str:
        return "3 Oaks: fila inválida" if game.provider != self.key or not SLUG.fullmatch(game.slug) or game.url != ORIGIN + "/game/" + game.slug else ""

    def _thumbnail(self, game: Game, progress):
        parsed = urlparse(game.thumbnail_url)
        if parsed.hostname != "3oaks.com" or not parsed.path.startswith("/media/"):
            return
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            return
        target = self.game_dir(game) / ("thumbnail" + suffix)
        try:
            if not target.is_file():
                response = self.http.get(game.thumbnail_url, timeout=20)
                response.raise_for_status()
                if len(response.content) > 10_000_000:
                    raise ValueError("miniatura demasiado grande")
                with Image.open(BytesIO(response.content)) as image:
                    image.verify()
                target.write_bytes(response.content)
            game.thumbnail_path = str(target)
        except Exception as exc:
            progress(f"[{game.name}] miniatura pendiente ({type(exc).__name__}).")

    def crawl_catalog(self, *, stop_event: threading.Event, progress, max_pages: int = 100, on_game=None) -> list[Game]:
        self.set_catalog_authority(False, "crawl incompleto")
        limit = int(max_pages)
        page, total = 1, None
        games = {}
        raw_dir = self.provider_root / "catalog"
        raw_dir.mkdir(exist_ok=True)
        while not stop_event.is_set() and (total is None or page <= total) and (limit <= 0 or page <= limit):
            response = self.http.get(CATALOG_API, params={"page_num": page, "page_items_num": 15, "sort": "release_date:desc"}, timeout=30)
            response.raise_for_status()
            payload = response.json()
            rows = games_from_page(payload)
            pages = payload["data"].get("total_pages")
            if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1 or pages > 1000:
                raise ValueError("3 Oaks: total_pages inválido")
            if total is not None and pages != total:
                raise ValueError("3 Oaks: catálogo cambió durante la paginación")
            total = pages
            (raw_dir / f"page-{page:03d}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if not payload["data"]["items"]:
                raise ValueError("3 Oaks: página vacía antes del final")
            for game in rows:
                if game.slug in games:
                    raise ValueError("3 Oaks: paginación repitió un juego")
                games[game.slug] = game
                self._thumbnail(game, progress)
                self._save_metadata(game, thumbnail_url=game.thumbnail_url, thumbnail_path=game.thumbnail_path)
                if on_game:
                    on_game(game)
            progress(f"3 Oaks: página {page}/{total}, {len(games)} juegos.")
            page += 1
        complete = total is not None and page > total and not stop_event.is_set()
        self.set_catalog_authority(complete, "" if complete else "límite de páginas o crawl detenido")
        # One launcher describes all client families; no per-game demo sweep.
        if complete and games:
            try:
                representative = next(iter(games.values()))
                response = self.http.get(CATALOG_API + "/" + representative.slug + "/play", params={"lang": "en"}, timeout=30)
                response.raise_for_status()
                config = launcher_config(response.text)
                families = family_map(config)
                (self.provider_root / "families.json").write_text(json.dumps(families, indent=2), encoding="utf-8")
                for game in games.values():
                    self._save_metadata(game, family=families.get(game.slug, "unknown"))
            except Exception as exc:
                progress(f"3 Oaks: mapa de familias pendiente ({type(exc).__name__}).")
        progress(f"3 Oaks catálogo: {len(games)} juegos; autoridad={'sí' if complete else 'no'}.")
        return sorted(games.values(), key=lambda g: g.name.casefold())

    def _public_input_source(self, url: str, revision: str, timeout_s: float) -> str:
        # Reuse only the exact public URL/revision named by the current launcher.
        key = hashlib.sha256((url + '\n' + str(revision)).encode()).hexdigest()
        cache = self.provider_root / 'input-sources'
        cache.mkdir(exist_ok=True)
        path = cache / (key + '.js')
        if path.is_file() and revision:
            return path.read_text(encoding='utf-8')
        response = self.http.get(url, params={'_ts':revision}, timeout=timeout_s)
        response.raise_for_status()
        source = response.text
        if not source or len(source) > 10_000_000 or '<html' in source[:500].lower():
            raise ValueError('3 Oaks: fuente de inputs no es JavaScript público')
        if revision:
            path.write_text(source, encoding='utf-8')
        return source

    def test_game(self, game: Game, *, spins: int, timeout_s: float, stop_event: threading.Event, progress) -> GameTestResult:
        requested = max(1, int(spins))
        result = GameTestResult(self.key, game.slug, game.name, game.url, requested, 0, 0, "PARCIAL", symbol=game.symbol)
        if stop_event.is_set():
            result.error = "Ejecución detenida"
            return result
        start_time = time.monotonic()
        browser_transport = None
        root = self.game_dir(game)
        run_dir = root / "tests" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
        run_dir.mkdir(parents=True)
        result.run_dir = str(run_dir)
        result.discovered_modes = self._metadata(game).get("discovered_modes", [])
        try:
            response = self.http.get(CATALOG_API + "/" + game.slug + "/play", params={"lang": "en"}, timeout=timeout_s)
            response.raise_for_status()
            (run_dir / "launcher.html").write_text(response.text, encoding="utf-8")
            config = launcher_config(response.text)
            options, desktop = config["options"], config["desktop"]
            family = client_family(desktop["client_url"])
            endpoint = desktop["server_url"].replace("{QUEUE}", str(options["queue"]))
            if endpoint.startswith("//"):
                endpoint = "https:" + endpoint
            parsed = urlparse(endpoint)
            if parsed.scheme != "https" or parsed.hostname != "betman-demo.head.3oaks.com" or not parsed.path.endswith("/demo/") or options.get("wl") != "demo" or options.get("protocol") != "goreel":
                raise ValueError("3 Oaks: launcher fuera del contrato demo observado")
            from .browser_transport import BrowserDemoTransport
            browser_transport = BrowserDemoTransport(game.url)
            session = DemoSession(self.http, endpoint, run_dir, timeout_s, browser_fallback=browser_transport)
            login = session.post("login", {"token": options["token"], "language": options.get("lang", "en")})
            if not session.session_id:
                raise ValueError("3 Oaks: login no devolvió session_id")
            data = session.post("start", {"mode": "auto", "huid": login.get("user", {}).get("huid")})
            asset = self.http.get(desktop["client_url"] + "src/game.js", timeout=timeout_s)
            asset.raise_for_status()
            (root / "client.js").write_text(asset.text, encoding="utf-8")
            from .client_contracts import client_contract
            client_profile = client_contract(asset.text, data=data)
            if ((client_profile or {}).get('spin_params') == ['bet_per_line', 'lines', 'bet_factor']
                    or (not (client_profile or {}).get('spin_params') and config.get('gr', {}).get('static_path'))):
                gr = config.get('gr', {})
                runner_url = str(gr.get('static_path', '')) + 'gr.js'
                runner_location = urlparse(runner_url)
                if runner_location.scheme != 'https' or runner_location.hostname != 'static.3oaks.com' or not runner_location.path.startswith('/gs/gamerunner/'):
                    raise ValueError('3 Oaks: ruta activa del spin pendiente de verificación')
                init_source = self._public_input_source(desktop['client_url'] + 'init.js', desktop.get('revision',''), timeout_s)
                runner_source = self._public_input_source(runner_url, gr.get('revision',''), timeout_s)
                (run_dir / 'client-init.js').write_text(init_source, encoding='utf-8')
                (run_dir / 'shared-runner.js').write_text(runner_source, encoding='utf-8')
                client_profile = client_contract(asset.text, data=data, runner_source=runner_source, init_source=init_source)
                if (client_profile or {}).get('spin_route') != 'shared-runner-button':
                    # A bundled default handler is not evidence of the active normal button.
                    if client_profile:
                        client_profile.pop('spin_params', None)

            source_rules = source_continuation_rules(asset.text)
            if client_profile:
                source_rules.update(client_profile.get('continuations', {}))
                (run_dir / 'client-input-contract.json').write_text(json.dumps(client_profile, indent=2), encoding='utf-8')
            (run_dir / 'client-continuation-contract.json').write_text(json.dumps({
                'client_sha256': hashlib.sha256(asset.text.encode()).hexdigest(), 'rules': source_rules}, indent=2), encoding='utf-8')
            # Require each client's public serializer, not just a vendor label.
            profile = client_profile or {}
            observed = bool(profile.get('spin_params'))
            modes = discover_modes(data, family, observed, client_profile=profile)
            for mode in modes:
                if mode["kind"] == "PURCHASE" and mode.get('selected_mode') not in profile.get('purchase_modes', []):
                    mode["executable"] = False
                    mode["reason"] = "PURCHASE_SERIALIZER_CAPTURE_REQUIRED"
                    if profile.get('purchase_ui_observed') and mode.get('selected_mode') in profile.get('purchase_ui_modes', data.get('context', {}).get('available_buy_bonus', [])):
                        mode.update(client_observed=True, evidence_level='CLIENT_INPUT_CALL',
                                    coverage_required=True)
                    else:
                        mode.update(declared=True, coverage_required=True,
                                    evidence_level='SERVER_ADVERTISED', client_observed=False)
                elif mode['kind'] == 'PURCHASE':
                    mode['client_observed'] = True
                    wire_values = profile.get('purchase_wire_values', {}).get(str(mode['selected_mode']))
                    if wire_values is not None:
                        mode['request_options'] = dict(wire_values)
                elif mode['kind'] == 'UNKNOWN_FEATURE':
                    mode['coverage_required'] = True
            result.discovered_modes = modes
            from tester_spin.feature_domains import initialization_domains
            result.feature_domains = initialization_domains("3oaks", data, modes)
            self._save_metadata(game, family=family, vendor=options.get("vendor"),
                                runtime_transport="goreel-http-commands", discovered_modes=modes)
            if not observed:
                result.error = "3 Oaks: formato del spin normal sin una ruta activa certificada"
                return result
            # Purchases are tried once each; never enumerate selector guesses.
            jobs = [(modes[0], None)] * requested + [(m, m['selected_mode'] if m['kind']=='PURCHASE' else m['ante_bet'])
                    for m in modes[1:] if m['kind'] in {'PURCHASE','ANTE_BET'} and m['executable']]
            def finish_round(current, directory, deadline):
                steps = 0
                while not base_terminal(current):
                    if stop_event.is_set() or steps >= 80 or time.monotonic() >= deadline:
                        return current, steps, False
                    next_fields = continuation_fields(current, game_slug=game.slug, family=family, client_profile=client_profile, source_rules=source_rules)
                    if next_fields is None:
                        return current, steps, False
                    saved_settings = current.get('settings', {})
                    current = session.post('play', next_fields, artifact_dir=directory)
                    current.setdefault('settings', saved_settings)
                    steps += 1
                return current, steps, True
            if not base_terminal(data):
                data, _, restored = finish_round(data, run_dir / 'initial-continuation',
                                                 time.monotonic() + min(90, max(20, timeout_s * 4)))
                if not restored:
                    result.error = '3 Oaks: continuación inicial no soportada por el contrato del cliente'
                    return result
            for mode, selector in jobs:
                if stop_event.is_set():
                    result.error = "Ejecución detenida"
                    break
                action = mode["wire_action"]
                fields = play_fields(data, action, selector if mode['kind']=='PURCHASE' else None,
                                     game_slug=game.slug, family=family, client_profile=client_profile,
                                     antebet=selector if mode['kind']=='ANTE_BET' else None)
                if mode['kind'] == 'PURCHASE':
                    try:
                        fields = affordable_purchase_fields(data, fields, selector)
                    except ValueError as budget_error:
                        if 'DEMO_BALANCE_INSUFFICIENT' not in str(budget_error):
                            raise
                        # A new official demo avoids spending the balance of previous tests.
                        session = DemoSession(self.http, endpoint, run_dir / f'purchase-session-{selector}', timeout_s, browser_fallback=browser_transport)
                        login = session.post('login', {'token':options['token'], 'language':options.get('lang','en')})
                        data = session.post('start', {'mode':'auto', 'huid':login.get('user',{}).get('huid')})
                        if not base_terminal(data):
                            data, _, restored = finish_round(data, run_dir / f'purchase-session-{selector}' / 'initial-continuation', time.monotonic()+min(90,max(20,timeout_s*4)))
                            if not restored:
                                raise ValueError('3 Oaks: new demo continuation pending')
                        fields = affordable_purchase_fields(data, play_fields(data, action, selector, game_slug=game.slug, family=family, client_profile=client_profile), selector)
                previous_settings = data.get("settings", {})
                attempt_dir = run_dir / f"attempt-{len(result.attempts) + 1:03d}"
                data = session.post("play", fields, artifact_dir=attempt_dir)
                data.setdefault("settings", previous_settings)
                feature_round = mode['kind'] in {'PURCHASE','ANTE_BET'} or not base_terminal(data)
                deadline = time.monotonic() + min(90, max(20, timeout_s * 4))
                data, extra_steps, terminal = finish_round(data, attempt_dir, deadline)
                wire_steps = 1 + extra_steps
                if terminal and feature_round:
                    audit_dir = attempt_dir / 'return-to-base'
                    consecutive = 0
                    for probe in range(1, 11):
                        if stop_event.is_set() or time.monotonic() >= deadline:
                            terminal = False
                            break
                        saved_settings = data.get('settings', {})
                        data = session.post('play', play_fields(data, 'spin', game_slug=game.slug, family=family, client_profile=client_profile),
                                            artifact_dir=audit_dir / f'probe-{probe:03d}')
                        data.setdefault('settings', saved_settings)
                        direct_base = base_terminal(data)
                        data, count, completed = finish_round(data, audit_dir / f'probe-{probe:03d}', deadline)
                        wire_steps += 1 + count
                        consecutive = consecutive + 1 if direct_base and completed else 0
                        if not completed:
                            break
                        if consecutive == 2:
                            break
                    terminal = terminal and consecutive == 2
                    (attempt_dir / 'return-to-base.json').write_text(json.dumps({
                        'status': 'CONFIRMED' if terminal else 'PENDING', 'required': 2,
                        'consecutive_base': consecutive}), encoding='utf-8')
                if terminal:
                    option = "spin" if mode["id"] == "SPIN" else str(selector)
                    mode["covered_options"] = [option]
                    counts = mode.setdefault("sample_counts", {})
                    counts[option] = counts.get(option, 0) + 1
                mode.update(observed=True, validated=terminal, evidence_level="REMOTE_EXECUTION",
                            execution_state="PROVEN_TERMINAL" if terminal else "CONTINUATION_PENDING")
                attempt = SpinAttempt(number=len(result.attempts) + 1, ok=terminal, mode_id=mode["id"], mode_kind=mode["kind"],
                    status_code=200, symbol=game.symbol, endpoint=endpoint, terminal=terminal,
                    wire_steps=wire_steps, artifact_dir=str(attempt_dir), warning="" if terminal else "Continuación o retorno a base pendiente")
                result.attempts.append(attempt)
                if mode["id"] == "SPIN":
                    result.successful_spins += int(terminal)
                progress(f"[{game.name}] {mode['id']}: {'OK' if terminal else 'PARCIAL'}.")
                if not terminal:
                    result.error = "3 Oaks: continuación pendiente; no se inventan parámetros"
                    break
            result.status = "OK" if result.successful_spins == requested and all(m.get("validated") for m in modes if m.get("coverage_required", True)) else "PARCIAL"
        except Exception as exc:
            result.status = "PARCIAL" if result.successful_spins else "ERROR"
            result.error = f"{type(exc).__name__}: {exc}"
            if '429' in str(exc):
                result.error = '3 Oaks: acceso HTTP 429 bloqueado por el sitio; no se pudo validar esta ejecución'
            progress(f"[{game.name}] 3 Oaks pendiente: {result.error}")
        finally:
            if browser_transport is not None:
                browser_transport.close()
            result.failed_spins = max(0, requested - result.successful_spins)
            result.finished_at = utc_now_iso()
            result.elapsed_ms = (time.monotonic() - start_time) * 1000
            self._save_metadata(game, discovered_modes=result.discovered_modes)
        return result

    def har_artifact_dir(self, game: Game):
        path = self.game_dir(game) / "analysis"
        path.mkdir(exist_ok=True)
        return path

    def farm_contract_dir(self, game: Game):
        return self.game_dir(game)

    def build_farm_contract(self, game: Game, result: GameTestResult) -> dict:
        return build_result_farm_contract(game, result, self.game_dir(game), _SPEC)

    def validate_farm_contract(self, contract: dict):
        return validate_result_farm_contract(contract, _SPEC)
