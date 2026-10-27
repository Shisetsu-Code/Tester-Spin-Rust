from __future__ import annotations

import json
import threading
from pathlib import Path

from curl_cffi import requests

from tester_spin.models import Game, GameTestResult
from tester_spin.providers.base import GameCallback, Progress, ProviderAdapter
from tester_spin.providers.ka_gaming.catalog import CATALOG_URL, declared_modes_from_row, games_from_catalog
from tester_spin.providers.ka_gaming.cooldown import ServerCooldown, ServerRetryAfter


class KAGamingProvider(ProviderAdapter):
    key = "ka_gaming"
    display_name = "KA Gaming"
    catalog_url = CATALOG_URL
    min_catalog_reconcile_ratio = 0.80

    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)
        self.provider_root = self.data_root / "providers" / self.key
        self.provider_root.mkdir(parents=True, exist_ok=True)
        from tester_spin.providers.ka_gaming.device_context import current_client_identity
        agent,_=current_client_identity()
        self.http = requests.Session(impersonate="chrome", headers={"Accept-Language": "es-ES,es;q=0.9","User-Agent":agent})
        self._modes_path = self.provider_root / "catalog_modes.json"
        self._catalog_modes = self._load_catalog_modes()

    def test_start_block_reason(self, *, timeout_s):
        metadata = ServerCooldown(self.provider_root).details()
        return str(ServerRetryAfter(metadata)) if metadata else ""

    def test_start_block_metadata(self):
        metadata = ServerCooldown(self.provider_root).details()
        return {"server_retry_after": metadata} if metadata else {}

    def _load_catalog_modes(self) -> dict[str, list[dict[str, object]]]:
        try:
            raw = json.loads(self._modes_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def crawl_catalog(self, *, stop_event: threading.Event, progress: Progress, max_pages: int = 100, on_game: GameCallback | None = None) -> list[Game]:
        del max_pages
        if stop_event.is_set():
            self.set_catalog_authority(False, "crawl detenido por el usuario")
            return []
        from tester_spin.providers.ka_gaming.limits import REQUEST_GATE
        cooldown = ServerCooldown(self.provider_root)
        cooldown.check(stop_event)
        REQUEST_GATE.acquire(stop_event)
        cooldown.check(stop_event)
        response = self.http.get(self.catalog_url, params={"lang": "es"}, headers={"Origin": "https://www.kaga88.com", "Referer": "https://www.kaga88.com/"}, timeout=30)
        cooldown.observe(response.status_code, getattr(response, "headers", {}), self.catalog_url)
        cooldown.check(stop_event)
        if response.status_code == 404:
            stop_event.set()
            progress("KA Gaming: HTTP 404; ejecuciÃ³n detenida.")
        response.raise_for_status()
        payload = response.json()
        games = games_from_catalog(payload, language="es")
        self._catalog_modes = {
            str(row["gameId"]).casefold(): declared_modes_from_row(row)
            for row in payload["games"]
            if isinstance(row, dict) and str(row.get("gameType") or "").casefold() == "slots"
        }
        self._modes_path.write_text(json.dumps(self._catalog_modes, ensure_ascii=False, indent=2), encoding="utf-8")
        if stop_event.is_set():
            self.set_catalog_authority(False, "crawl detenido por el usuario")
            return games
        self.set_catalog_authority(True)
        for game in games:
            if on_game: on_game(game)
        progress(f"KA Gaming catÃ¡logo terminado: {len(games)} juegos; autoridad=sÃ­.")
        return games

    def test_game(self, game: Game, *, spins: int, timeout_s: float, stop_event: threading.Event, progress: Progress) -> GameTestResult:
        from tester_spin.providers.ka_gaming.runtime import refresh_signing_profile, run_rmp_game
        try:
            profile = refresh_signing_profile(game, http=self.http, root=self.provider_root,
                timeout_s=timeout_s, stop_event=stop_event, progress=progress)
        except Exception as exc:
            return GameTestResult(provider=self.key, slug=game.slug, game_name=game.name,
                game_url=game.url, requested_spins=spins, successful_spins=0, failed_spins=spins,
                status="ERROR", discovered_modes=self._discovered_modes(game),
                error=f"Actualización de cliente KA: {type(exc).__name__}: {exc}",
                structural_map={"server_retry_after": exc.metadata} if isinstance(exc, ServerRetryAfter) else {})
        if profile is not None:
            sources = {'common':'', 'client':''}
            try:
                import re
                from tester_spin.providers.ka_gaming.limits import REQUEST_GATE
                if not re.fullmatch(r'[A-Za-z0-9_-]+', game.symbol or ''):
                    raise ValueError('KA: simbolo de cliente invalido')
                sources['common'] = (self.provider_root/'runtime'/('game.min.'+profile[0]+'.js')).read_text(encoding='utf-8')
                cooldown = ServerCooldown(self.provider_root)
                cooldown.check(stop_event)
                REQUEST_GATE.acquire(stop_event)
                cooldown.check(stop_event)
                response = self.http.get('https://gamesdemo.kaga88.com/res/js/'+profile[0]+'/'+game.symbol.lower()+'.js',timeout=timeout_s)
                cooldown.observe(response.status_code, getattr(response, 'headers', {}), 'https://gamesdemo.kaga88.com/res/js/'+profile[0]+'/'+game.symbol.lower()+'.js')
                cooldown.check(stop_event)
                response.raise_for_status()
                sources['client'] = response.text
            except Exception as exc:
                progress('KA: declaracion del cliente pendiente ('+type(exc).__name__+').')
            return run_rmp_game(game, http=self.http, root=self.provider_root, profile=profile,
                modes=self._discovered_modes(game), capabilities=sources, spins=spins, timeout_s=timeout_s,
                stop_event=stop_event, progress=progress)
        progress(f"[{game.name}] KA Gaming: transporte WebSocket confirmado; falta capturar vds de una sesiÃ³n para ejecutar el spin.")
        return GameTestResult(
            provider=self.key,
            slug=game.slug,
            game_name=game.name,
            game_url=game.url,
            symbol=game.symbol,
            requested_spins=spins,
            successful_spins=0,
            failed_spins=0,
            status="PARCIAL",
            error="KA Gaming: WebSocket y mensaje de giro confirmados, pero vds es una credencial de sesiÃ³n efÃ­mera; no se enviÃ³ apuesta fuera del navegador.",
            discovered_modes=self._discovered_modes(game),
        )

    def _discovered_modes(self, game: Game) -> list[dict[str, object]]:
        declared = [dict(mode) for mode in self._catalog_modes.get(game.slug, [])]
        if not declared:
            declared = [{"id": "SPIN", "kind": "SLOTS", "source": "fallback", "executable": False, "coverage_required": False}]
        for mode in declared:
            if mode["id"] == "BONUS_PURCHASE":
                mode.update(id="BONUS_FEATURE_UNCLASSIFIED", kind="FEATURE",
                            coverage_required=False, executable=False, observed=False,
                            reason="LEGACY_CATALOG_BP_IS_AMBIGUOUS")
            if mode["id"] == "SPIN":
                mode.update({
                    "reason": "SESSION_VDS_CAPTURE_REQUIRED",
                    "transport": "websocket+rmp-http",
                    "endpoint_template": "wss://pml{host}/kaga/fish/{gameId}?vds=<session>&ak=accessKey",
                    "request_type": "fr",
                    "request_fields": ["rt", "mid", "a", "l", "c", "b", "bt"],
                    # Playwright asset evidence from a real normal spin in both
                    # CapyGo123 (lines) and GoldenBull (ways).  `ctx` and the
                    # startGame response remain session-bound, so this is a
                    # discovered candidate rather than an executable contract.
                    "rmp_spin": {
                        "method": "POST",
                        "endpoint_template": "https://rmp{host}/kaga/command/spin?ak=<accessKey>&cr=<currency>&m=<mode>&u=<user>",
                        "content_type": "application/json",
                        "request_fields": ["gn", "sel", "sid", "cps", "atb", "dn", "psp?", "pos?"],
                        "required_header": "ctx",
                        "evidence": ["CapyGo123", "GoldenBull"],
                    },
                    "rmp_start_game": {
                        "method": "POST",
                        "endpoint_template": "https://rmp{host}/kaga/rmp/startGame?ak=<accessKey>&cr=<currency>&m=<mode>&u=<user>",
                        "content_type": "application/json",
                        "request_fields": ["on?", "un", "pn", "ak", "gn", "loc", "to", "cr", "gm", "tb", "mi", "mc", "psp?", "jrd?", "to2?"],
                        "required_header": "ctx",
                        "ctx_fields": ["u?", "c?", "dt?", "dv?", "av", "ida", "idv", "lg", "do", "as", "ak"],
                        "signature": "sha256(client-side signed ctx; timestamp-bound)",
                        "returns": ["sid", "cps", "sel", "psp?"],
                        "evidence": "game.min.2070.js: Bca, Fc.G8e, Cc.I9e",
                    },
                })
            else:
                mode.setdefault("reason", "WIRE_CONTRACT_NOT_OBSERVED")
        try:
            imported = json.loads((self.provider_root / game.slug / "purchase_modes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            imported = []
        for mode in imported if isinstance(imported, list) else []:
            if isinstance(mode, dict) and mode.get("id") == "BUY_POS_1" and mode.get("pos") == [1] and mode.get("source") == "manual-har":
                declared = [m for m in declared if m["id"] not in {"BONUS_PURCHASE", "BUY_POS_1"}]
                declared.append({**mode, "validated": False, "executable": False})
        return declared
