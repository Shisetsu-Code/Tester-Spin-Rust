from __future__ import annotations

from tester_spin.return_to_base import audit_enabled, audit_blocked, pending_return

import base64
import json
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from tester_spin.providers.one_spin4win_purchases import discover_purchase_modes, discover_antebet_modes, apply_purchase_coverage, purchase_modes_for_init, classify_spin_message
from tester_spin.providers.one_spin4win_purchases import discover_paid_contract, bind_paid_contract_init, legacy_ante_cost, verify_ante_debit
from tester_spin.models import Game, GameTestResult, SpinAttempt, utc_now_iso
from tester_spin.providers.base import GameCallback, Progress, ProviderAdapter


_ONE_SPIN_LOCAL = threading.local()
_DEMO_HOST = "gs.1spin4win.com"


def _safe_folder(name: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", str(name).strip()).rstrip(" .")
    return value[:160] or "Unnamed Game"


def _slug_title(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


class OneSpin4WinProvider(ProviderAdapter):
    """1spin4win/D1 adapter.

    The official public portfolio observed in the supplied Firefox HAR is a
    Webflow CMS catalogue rendered as HTML. Pagination is exposed through the
    real Webflow next-page link (e.g. ?ae0c3ebe_page=2), so catalogue crawling
    is direct HTTP and does not click the UI.

    Game runtime remains WebSocket-oriented: the demo shell is opened only to
    observe the functional sockets/frames. No HTTP response is treated as a
    validated wager/spin result.
    """

    key = "1spin4win"
    display_name = "1spin4win (D1)"
    catalog_url = "https://www.1spin4win.com/games"

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.provider_root = data_root / "providers" / self.key
        self.provider_root.mkdir(parents=True, exist_ok=True)
        self.http = requests.Session()
        self.http.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }
        )

    def game_dir(self, game: Game) -> Path:
        path = self.provider_root / _safe_folder(game.name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _worker_session(self) -> requests.Session:
        session = getattr(_ONE_SPIN_LOCAL, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(dict(self.http.headers))
            try:
                session.cookies.update(self.http.cookies.get_dict())
            except Exception:
                pass
            _ONE_SPIN_LOCAL.session = session
        return session

    @staticmethod
    def _demo_symbol(demo_url: str) -> str:
        parsed = urlparse(demo_url)
        query = parse_qs(parsed.query)
        explicit = (query.get("game") or [""])[0].strip()
        if explicit:
            return explicit
        stem = Path(parsed.path).stem.strip()
        return "" if stem.casefold() == "games" else stem

    @staticmethod
    def _best_card_image(card: Tag, base_url: str) -> str:
        img = card.select_one("img.image_portfolio-game")
        if img is None:
            img = card.find("img")
        if img is None:
            return ""
        for key in ("src", "data-src", "data-lazy-src"):
            value = str(img.get(key) or "").strip()
            if value and not value.startswith("data:"):
                return urljoin(base_url, value)
        srcset = str(img.get("srcset") or img.get("data-srcset") or "")
        choices = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
        return urljoin(base_url, choices[-1]) if choices else ""

    def _extract_catalog_page(
        self,
        html: str,
        base_url: str,
    ) -> tuple[list[Game], str]:
        """Parse the exact Webflow catalogue structure observed in the D1 HAR."""
        soup = BeautifulSoup(html or "", "html.parser")
        found: dict[str, Game] = {}

        for card in soup.select("div.item_portfolio"):
            if not isinstance(card, Tag):
                continue

            detail = card.select_one("a.link_portfolio-game[href]")
            name_node = card.select_one('[fs-list-field="name"]')
            slug_node = card.select_one('[fs-list-field="slug"]')
            demo_link: Tag | None = None
            for anchor in card.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                if (urlparse(urljoin(base_url, href)).hostname or "").casefold() == _DEMO_HOST:
                    demo_link = anchor
                    break

            detail_url = (
                urljoin(base_url, str(detail.get("href") or ""))
                if isinstance(detail, Tag)
                else ""
            )
            slug = (
                " ".join(slug_node.stripped_strings).strip().casefold()
                if isinstance(slug_node, Tag)
                else ""
            )
            if not slug and detail_url:
                path = urlparse(detail_url).path.rstrip("/")
                slug = path.rsplit("/", 1)[-1].casefold()
            if not slug:
                continue

            name = (
                " ".join(name_node.stripped_strings).strip()
                if isinstance(name_node, Tag)
                else ""
            )
            if not name:
                image = card.select_one("img.image_portfolio-game")
                name = str(image.get("alt") or "").strip() if isinstance(image, Tag) else ""
            if not name:
                name = _slug_title(slug)

            demo_url = (
                urljoin(base_url, str(demo_link.get("href") or ""))
                if isinstance(demo_link, Tag)
                else ""
            )
            # Tester-Spin must open the actual demo runtime for protocol discovery.
            # If a demo is unavailable, keep the detail page as a diagnostic fallback.
            launch_url = demo_url or detail_url
            symbol = self._demo_symbol(demo_url) if demo_url else ""

            found[slug] = Game(
                provider=self.key,
                slug=slug,
                name=name,
                url=launch_url,
                thumbnail_url=self._best_card_image(card, base_url),
                symbol=symbol,
            )

        next_link = soup.select_one("a.w-pagination-next[href]")
        next_url = ""
        if isinstance(next_link, Tag):
            next_url = urljoin(base_url, str(next_link.get("href") or "").strip())

        return list(found.values()), next_url

    def _persist_thumbnail(self, game: Game, progress: Progress) -> None:
        if not game.thumbnail_url:
            return
        root = self.game_dir(game)
        suffix = Path(urlparse(game.thumbnail_url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            suffix = ".img"
        target = root / f"thumbnail{suffix}"
        if target.exists() and target.stat().st_size > 0:
            game.thumbnail_path = str(target)
            return
        try:
            response = self._worker_session().get(game.thumbnail_url, timeout=20.0)
            response.raise_for_status()
            target.write_bytes(response.content)
            game.thumbnail_path = str(target)
        except Exception as exc:
            progress(f"[{game.name}] miniatura: {type(exc).__name__}: {exc}")

    def crawl_catalog(
        self,
        *,
        stop_event: threading.Event,
        progress: Progress,
        max_pages: int = 100,
        on_game: GameCallback | None = None,
    ) -> list[Game]:
        limit = int(max_pages)
        if limit <= 0:
            limit = 1000

        by_slug: dict[str, Game] = {}
        visited: set[str] = set()
        page_no = 1
        url = self.catalog_url
        raw_dir = self.provider_root / "catalog-pages"
        raw_dir.mkdir(parents=True, exist_ok=True)

        progress(
            "D1 catálogo HAR: Webflow HTTP paginado; siguiendo el href real de "
            "'cargar más' sin interacción gráfica."
        )

        while url and page_no <= limit and not stop_event.is_set():
            if url in visited:
                progress(f"D1 catálogo: ciclo de paginación detectado en {url}")
                break
            visited.add(url)

            response = self.http.get(url, timeout=30.0, allow_redirects=True)
            response.raise_for_status()
            (raw_dir / f"page-{page_no:03d}.html").write_text(
                response.text,
                encoding="utf-8",
                errors="replace",
            )

            page_games, next_url = self._extract_catalog_page(response.text, response.url)
            new_count = 0
            for game in page_games:
                if game.slug in by_slug:
                    continue
                by_slug[game.slug] = game
                new_count += 1
                self._persist_thumbnail(game, progress)
                if on_game is not None:
                    on_game(game)
                progress(
                    f"  + D1 {game.name} [{game.symbol or game.slug}] — {game.url}"
                )

            progress(
                f"D1 página {page_no}: juegos={len(page_games)}, "
                f"nuevos={new_count}, total={len(by_slug)}, "
                f"siguiente={'sí' if next_url else 'no'}"
            )

            if not page_games:
                break
            url = next_url
            page_no += 1

        games = sorted(by_slug.values(), key=lambda game: game.name.casefold())
        (self.provider_root / "catalog.json").write_text(
            json.dumps(
                [
                    {
                        "provider": game.provider,
                        "slug": game.slug,
                        "name": game.name,
                        "url": game.url,
                        "thumbnail_url": game.thumbnail_url,
                        "thumbnail_path": game.thumbnail_path,
                        "symbol": game.symbol,
                        "catalog_transport": "webflow_html",
                        "runtime_transport": "websocket",
                    }
                    for game in games
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        progress(f"Catálogo D1 terminado: {len(games)} juegos únicos.")
        return games

    @staticmethod
    def _frame_preview(payload: object, *, limit: int = 16384) -> dict[str, object]:
        if isinstance(payload, bytes):
            raw = payload[:limit]
            return {
                "kind": "binary",
                "size": len(payload),
                "base64": base64.b64encode(raw).decode("ascii"),
                "truncated": len(payload) > limit,
            }
        text = str(payload)
        return {
            "kind": "text",
            "size": len(text),
            "text": text[:limit],
            "truncated": len(text) > limit,
        }

    @staticmethod
    def _decode_ws_json(payload: object) -> Any | None:
        if isinstance(payload, bytes):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                return None
        else:
            text = str(payload)
        text = text.strip()
        if not text:
            return None

        candidates = [text]
        starts = [index for index, char in enumerate(text[:64]) if char in "[{"]
        candidates.extend(text[index:] for index in starts if index > 0)

        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _is_webvisor_payload(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        query = value.get("query")
        if isinstance(query, dict):
            qkeys = {str(key).casefold() for key in query}
            if {"wv-type", "wv-check", "wv-hit"} & qkeys:
                return True
        if (
            str(value.get("resource") or "").casefold() in {"events", "webvisor"}
            and value.get("wstoken")
        ):
            body = value.get("body")
            if isinstance(body, list):
                return any(
                    isinstance(item, dict) and str(item.get("event") or "") == "sessionStart"
                    for item in body
                )
        return False

    @staticmethod
    def _is_noise_websocket_url(url: str) -> bool:
        host = (urlparse(url).hostname or "").casefold()
        return (
            host.endswith("yandex.ru")
            or host.endswith("yandex.net")
            or "metrika" in host
            or "webvisor" in host
            or host.endswith("google-analytics.com")
            or host.endswith("googletagmanager.com")
            or host.endswith("doubleclick.net")
        )

    @staticmethod
    def _parse_runtime_source(text: str) -> tuple[str, list[str]]:
        source = text or ""
        ws_url = ""
        match = re.search(
            r"""gameURL\s*=\s*["'](wss?://[^"']+)["']""",
            source,
            re.I,
        )
        if not match:
            # Some D1 titles build the config differently but still contain the
            # final socket literal somewhere in a bundled/minified asset.
            match = re.search(r"""["'](wss?://[^"'\\s]+)["']""", source, re.I)
        if match:
            ws_url = match.group(1).strip()

        connect_args: list[str] = []
        match = re.search(
            r"""gameController\.connect\s*\(([^;]{1,500})\)""",
            source,
            re.I | re.S,
        )
        if match:
            connect_args = re.findall(r"""["']([^"']*)["']""", match.group(1))
        return ws_url, connect_args

    @staticmethod
    def _parse_observed_init_wire(payload: object) -> dict[str, str] | None:
        if isinstance(payload, bytes):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                return None
        else:
            text = str(payload)

        if not text.startswith("A/u2"):
            return None
        try:
            envelope = json.loads(text[4:])
        except json.JSONDecodeError:
            return None
        if str(envelope.get("type")) != "0":
            return None

        fields = str(envelope.get("data") or "").split(",")
        if len(fields) < 7 or fields[2].casefold() != "freeplay":
            return None
        game_name = fields[3].strip()
        version = fields[4].strip()
        wallet = fields[5].strip()
        currency = fields[6].strip()
        if not game_name or not version:
            return None
        return {
            "game_name": game_name,
            "version": version,
            "wallet": wallet,
            "currency": currency,
        }

    def _observe_runtime_bootstrap(
        self,
        entry_url: str,
        *,
        timeout_s: float,
        attempt_dir: Path,
    ) -> dict[str, Any]:
        observed: dict[str, Any] = {
            "ws_url": "",
            "game_name": "",
            "version": "",
            "wallet": "",
            "currency": "",
            "frames": [],
            "error": "",
        }
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                def on_websocket(ws) -> None:
                    ws_url = str(ws.url)
                    if self._is_noise_websocket_url(ws_url):
                        return
                    if not observed["ws_url"]:
                        observed["ws_url"] = ws_url

                    def on_sent(payload) -> None:
                        if len(observed["frames"]) < 80:
                            observed["frames"].append(
                                {
                                    "direction": "sent",
                                    "websocket_url": ws_url,
                                    "payload": self._frame_preview(payload),
                                }
                            )
                        init = self._parse_observed_init_wire(payload)
                        if init:
                            for key, value in init.items():
                                if value and not observed.get(key):
                                    observed[key] = value

                    def on_received(payload) -> None:
                        if len(observed["frames"]) < 80:
                            observed["frames"].append(
                                {
                                    "direction": "received",
                                    "websocket_url": ws_url,
                                    "payload": self._frame_preview(payload),
                                }
                            )

                    ws.on("framesent", on_sent)
                    ws.on("framereceived", on_received)

                page.on("websocket", on_websocket)
                page.goto(
                    entry_url,
                    wait_until="domcontentloaded",
                    timeout=max(1_000, int(timeout_s * 1000)),
                )

                deadline = time.monotonic() + min(max(timeout_s, 3.0), 12.0)
                while time.monotonic() < deadline:
                    if (
                        observed["ws_url"]
                        and observed["game_name"]
                        and observed["version"]
                    ):
                        break
                    page.wait_for_timeout(200)

                context.close()
                browser.close()
        except Exception as exc:
            observed["error"] = f"{type(exc).__name__}: {exc}"

        (attempt_dir / "runtime-bootstrap-observed.json").write_text(
            json.dumps(observed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return observed

    @staticmethod
    def _script_references(text: str) -> list[str]:
        refs: list[str] = []
        patterns = (
            r"""addJSFile\s*\(\s*["']([^"']+)["']\s*\)""",
            r"""script\.src\s*=\s*["']([^"']+)["']""",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text or "", re.I):
                value = match.group(1).strip()
                if value and value not in refs:
                    refs.append(value)
        return refs

    def _discover_runtime_spec(
        self,
        game: Game,
        *,
        timeout_s: float,
        attempt_dir: Path,
    ) -> dict[str, Any]:
        session = self._worker_session()
        response = session.get(game.url, timeout=timeout_s, allow_redirects=True)
        response.raise_for_status()
        launcher = urlparse(response.url)
        launcher_query = parse_qs(launcher.query, keep_blank_values=True)
        if launcher.hostname == 'gs.1spin4win.com' and launcher.path == '/gmh5/games.html':
            values = launcher_query.pop('game', [])
            if len(values) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', values[0]):
                raise RuntimeError('D1: el lanzador no contiene un identificador de juego válido.')
            # games_000101.js performs this same redirect on window.onload.
            target = urljoin(response.url, values[0].lower() + '.html')
            target += '?' + urlencode(launcher_query, doseq=True)
            response = session.get(target, timeout=timeout_s, allow_redirects=True)
            response.raise_for_status()
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "demo-page.html").write_text(
            response.text,
            encoding="utf-8",
            errors="replace",
        )

        parsed_demo = urlparse(response.url)
        origin = f"{parsed_demo.scheme}://{parsed_demo.netloc}"
        query = parse_qs(parsed_demo.query)
        freeplay = (query.get("freeplay") or [""])[0].casefold() == "true"
        if not freeplay:
            raise RuntimeError(
                "D1 direct WS sólo está habilitado para la demo pública freeplay."
            )

        soup = BeautifulSoup(response.text or "", "html.parser")
        queue: list[str] = []
        ws_url, connect_args = self._parse_runtime_source(response.text)
        for node in soup.find_all("script", src=True):
            src = urljoin(response.url, str(node.get("src") or ""))
            if src and src not in queue:
                queue.append(src)

        purchase_sources = [response.text]
        scanned: list[str] = []
        failed_assets: list[str] = []
        while queue and len(scanned) < 32:
            src = queue.pop(0)
            if src in scanned:
                continue
            scanned.append(src)
            try:
                js = session.get(src, timeout=min(timeout_s, 20.0), allow_redirects=True)
                js.raise_for_status()
                if len(js.content) > 8 * 1024 * 1024:
                    failed_assets.append(src)
                    continue
                text = js.text
                purchase_sources.append(text)
            except Exception:
                failed_assets.append(src)
                continue

            candidate_ws, candidate_args = self._parse_runtime_source(text)
            if candidate_ws and not ws_url:
                ws_url = candidate_ws
            if len(candidate_args) >= 7 and not connect_args:
                connect_args = candidate_args[:7]

            # These paths are inserted into the document by the loader, so they
            # resolve against the demo document URL, not against the loader file.
            for ref in self._script_references(text):
                child = urljoin(response.url, ref)
                if child not in scanned and child not in queue:
                    queue.append(child)

        static_ws_found = bool(ws_url)
        static_connect_found = len(connect_args) >= 7
        observed: dict[str, Any] = {}
        if not static_ws_found or not static_connect_found:
            observed = self._observe_runtime_bootstrap(
                response.url,
                timeout_s=timeout_s,
                attempt_dir=attempt_dir,
            )
            if not ws_url:
                ws_url = str(observed.get("ws_url") or "").strip()

        if len(connect_args) >= 7:
            game_name = connect_args[0].strip()
            version = connect_args[4].strip()
            wallet = connect_args[5].strip()
            currency = connect_args[6].strip()
        else:
            game_name = str(observed.get("game_name") or "").strip()
            version = str(observed.get("version") or "").strip()
            wallet = str(observed.get("wallet") or "").strip()
            currency = str(observed.get("currency") or "").strip()

        wallet = (query.get("config") or [wallet])[0].strip()
        currency = (query.get("currency") or [currency])[0].strip()

        if not ws_url:
            detail = str(observed.get("error") or "").strip()
            raise RuntimeError(
                "D1: no se resolvió WebSocket ni desde assets ni observando runtime"
                + (f" ({detail})" if detail else ".")
            )
        if not game_name or not version:
            raise RuntimeError(
                "D1: no se resolvió gameName/version ni desde JS ni desde el init WS observado."
            )
        if not currency:
            currency = "EUR"

        paid_contract = discover_paid_contract(purchase_sources, game_name, assets_complete=not failed_assets and not queue)
        spec = {
            "ws_url": ws_url,
            "origin": origin,
            "game_name": game_name,
            "version": version,
            "wallet": wallet,
            "currency": currency,
            "freeplay": True,
            "demo_url": response.url,
            "scripts_scanned": scanned,
            "purchase_modes": paid_contract['purchase_modes'],
            "antebet_modes": paid_contract['antebet_modes'],
            "paid_client_contract": paid_contract,
            "failed_assets": failed_assets,
            "discovery": {
                "ws_from_static_assets": static_ws_found,
                "connect_from_static_assets": static_connect_found,
                "runtime_fallback_used": bool(observed),
                "runtime_fallback_ws_url": (
                    str(observed.get("ws_url") or "") if observed else ""
                ),
                "runtime_fallback_error": (
                    str(observed.get("error") or "") if observed else ""
                ),
            },
        }
        (attempt_dir / "runtime-spec.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return spec

    def _open_websocket(self, spec: dict[str, Any], timeout_s: float):
        import websocket

        cookie = "; ".join(
            f"{name}={value}"
            for name, value in self._worker_session().cookies.get_dict().items()
        )
        return websocket.create_connection(
            str(spec["ws_url"]),
            timeout=max(1.0, float(timeout_s)),
            origin=str(spec["origin"]),
            cookie=cookie or None,
            header=[
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) "
                "Gecko/20100101 Firefox/155.0"
            ],
        )

    @staticmethod
    def _wire_message(message_type: str, data: str, *, key: str = "") -> str:
        return "A/u2" + json.dumps(
            {"key": key, "type": str(message_type), "data": data},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _int_field(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    # Official SlotNetworkController.parseGameData in tenluckyspins_000264.js:
    # st=3 leaves bonusSpins=false; the result view enables the next paid spin.
    # Live state-3 captures independently show b_next = b_previous - bet + win.
    D1_TERMINAL_STATES = frozenset({0, 3})
    D1_CONTRACT_SOURCE = "https://gs.1spin4win.com:10443/gmh5/tenluckyspins/src/tenluckyspins_000264.js"

    @classmethod
    def _d1_result_terminal(cls, payload: dict[str, Any]) -> bool:
        # Missing st follows the legacy client default (no bonusSpins).
        state = cls._int_field(payload.get("st", 0), -1)
        total = cls._int_field(payload.get("b9"), -1)
        current = cls._int_field(payload.get("b8"), -1)
        return state in cls.D1_TERMINAL_STATES or (state == 12 and total > 0 and current == total)

    @classmethod
    def _d1_feature_active(cls, payload: dict[str, Any]) -> bool:
        state = cls._int_field(payload.get("st"), 0)
        return state in {5, 6, 11, 12} and not cls._d1_result_terminal(payload)

    def _recv_protocol_json(
        self,
        ws,
        *,
        deadline: float,
        frames: list[dict[str, Any]],
    ) -> dict[str, Any]:
        while time.monotonic() < deadline:
            raw = ws.recv()
            frames.append(
                {
                    "direction": "received",
                    "payload": self._frame_preview(raw),
                }
            )
            if raw == "pns":
                pong = "A/pns"
                ws.send(pong)
                frames.append(
                    {
                        "direction": "sent",
                        "payload": self._frame_preview(pong),
                        "classification": "keepalive",
                    }
                )
                continue
            decoded = self._decode_ws_json(raw)
            from tester_spin.server_observations import observe_live
            observe_live(decoded if decoded is not None else raw, action="ws:"+str(decoded.get("type", "unknown")) if isinstance(decoded, dict) else "ws")
            if isinstance(decoded, dict):
                return decoded
        raise TimeoutError("D1: timeout esperando frame JSON del servidor.")

    def _execute_direct_ws_spin(
        self,
        game: Game,
        *,
        timeout_s: float,
        attempt_dir: Path,
        wire_guard: int = 128,
        feature_selector: int | None = None,
        feature_kind: str = "PURCHASE",
    ) -> tuple[bool, bool, float, str, list[dict[str, Any]], str]:
        if feature_kind not in {"PURCHASE", "ANTE_BET"}:
            raise ValueError("D1: modalidad de selector desconocida")
        started = time.monotonic()
        spec = self._discover_runtime_spec(
            game,
            timeout_s=timeout_s,
            attempt_dir=attempt_dir,
        )
        from tester_spin.server_observations import set_capture_directory
        set_capture_directory(attempt_dir)
        frames: list[dict[str, Any]] = []
        warning = ""
        ws = self._open_websocket(spec, timeout_s)
        try:
            init_data = (
                f",,freeplay,{spec['game_name']},{spec['version']},"
                f"{spec['wallet']},{spec['currency']},test"
            )
            init_wire = self._wire_message("0", init_data)
            ws.send(init_wire)
            frames.append(
                {
                    "direction": "sent",
                    "classification": "init",
                    "payload": self._frame_preview(init_wire),
                }
            )

            deadline = time.monotonic() + max(2.0, timeout_s)
            init_payload: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                payload = self._recv_protocol_json(
                    ws,
                    deadline=deadline,
                    frames=frames,
                )
                message_type = self._int_field(payload.get("type"), -1)
                if message_type == 2:
                    raise RuntimeError(
                        "D1 init error: "
                        + str(payload.get("error") or payload.get("errorCode") or payload)
                    )
                if message_type == 1:
                    init_payload = payload
                    break

            if init_payload is None:
                raise TimeoutError("D1: no llegó respuesta type=1 de inicialización.")

            bound = bind_paid_contract_init(spec['paid_client_contract'], init_payload)
            spec['paid_client_contract'] = bound
            spec['feature_domains'] = bound['feature_domains']
            spec['purchase_modes'] = bound['purchase_modes']
            spec['antebet_modes'] = bound['antebet_modes']
            (attempt_dir / "runtime-spec.json").write_text(
                json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            lines = self._int_field(init_payload.get("l"), 0)
            bet_index = self._int_field(init_payload.get("b3"), -1)
            if lines <= 0 or bet_index < 0:
                raise RuntimeError(
                    f"D1 init incompleto: l={init_payload.get('l')!r}, "
                    f"b3={init_payload.get('b3')!r}"
                )

            if feature_selector is not None:
                if not any(mode.get('executable') and mode.get('feature_selector') == feature_selector for mode in spec.get('antebet_modes' if feature_kind == 'ANTE_BET' else 'purchase_modes', [])):
                    raise RuntimeError('D1: compra deshabilitada o selector sin contrato en este juego.')
                if self._d1_feature_active(init_payload):
                    raise RuntimeError('D1: sesión con bonus activo; no se inicia otra compra.')
            ante_cost = None
            if feature_kind == 'ANTE_BET' and feature_selector is not None:
                selected = next(m for m in spec['antebet_modes'] if m.get('feature_selector') == feature_selector)
                if selected.get('requires_buy_feature') is False:
                    ante_cost = legacy_ante_cost(bound, init_payload)
            purchase_accepted = feature_selector is None or feature_kind == "ANTE_BET"
            result_payload: dict[str, Any] | None = None
            terminal = False
            steps = 0
            while steps < wire_guard:
                steps += 1
                play_data = f"{lines},{bet_index},0"
                if feature_selector is not None and steps == 1:
                    play_data += f",{feature_selector}"
                play_wire = self._wire_message("1", play_data)
                ws.send(play_wire)
                frames.append(
                    {
                        "direction": "sent",
                        "classification": (("antebet" if feature_kind == "ANTE_BET" else "purchase") if feature_selector is not None else "spin") if steps == 1 else "continuation",
                        "spin_shape": classify_spin_message({"type":"1", "data":play_data}, purchase_selectors={feature_selector} if feature_selector is not None and feature_kind == "PURCHASE" else set(), side_bet_selectors={feature_selector} if feature_selector is not None and feature_kind == "ANTE_BET" else set()),
                        "payload": self._frame_preview(play_wire),
                    }
                )

                result_deadline = time.monotonic() + max(2.0, timeout_s)
                while time.monotonic() < result_deadline:
                    payload = self._recv_protocol_json(
                        ws,
                        deadline=result_deadline,
                        frames=frames,
                    )
                    message_type = self._int_field(payload.get("type"), -1)
                    if message_type == 2:
                        raise RuntimeError(
                            "D1 spin error: "
                            + str(payload.get("error") or payload.get("errorCode") or payload)
                        )
                    if message_type == 3:
                        result_payload = payload
                        break
                if result_payload is None:
                    raise TimeoutError("D1: no llegó resultado type=3 de la tirada.")

                if ante_cost is not None and steps == 1:
                    verify_ante_debit(init_payload, result_payload, ante_cost)
                    (attempt_dir / 'ante-debit.json').write_text(json.dumps({'schema': 'd1/legacy-ante-debit/v1',
                        'cost': ante_cost, 'balance_before': init_payload['b'], 'balance_after': result_payload['b'],
                        'win': result_payload['w'], 'feature_selector': feature_selector}), encoding='utf-8')
                    if self._d1_feature_active(result_payload):
                        # The legacy ante debit is bound, but this family has no
                        # observed bonus-credit ledger yet. Do not infer final
                        # money from a later st=12 or send another paid command.
                        warning = 'D1: ANTE_FEATURE_LEDGER_UNBOUND; bonus pendiente de contrato contable.'
                        break

                if feature_selector is not None and feature_kind == "PURCHASE" and steps == 1:
                    current = self._int_field(result_payload.get('b8'), -1)
                    total = self._int_field(result_payload.get('b9'), -1)
                    purchase_accepted = self._d1_feature_active(result_payload) and total > 0 and 0 <= current <= total
                    if not purchase_accepted:
                        warning = 'D1: la solicitud de compra no inició un bonus reconocido.'
                        break
                settled_bonus = (result_payload.get('st') == 12
                                 and self._int_field(result_payload.get('b9'), -1) > 0
                                 and self._int_field(result_payload.get('b8'), -1) == self._int_field(result_payload.get('b9'), -2))
                if result_payload.get('st') == 12 and not settled_bonus:
                    warning = 'D1: cierre de bonus con contadores incompletos; no se envía otra apuesta.'
                    break
                if purchase_accepted and (self._d1_result_terminal(result_payload) or settled_bonus):
                    terminal = True
                    break
                if not self._d1_feature_active(result_payload):
                    warning = f"D1: estado type=3 sin contrato: {result_payload.get('st')!r}."
                    break

                # The official client continues bonus/free-spin states through the
                # same playGame() -> type=1 path. Reuse lines/betIndex and guard
                # against malformed or endless feature state.
                bet_index = self._int_field(result_payload.get("b3"), bet_index)
                lines = self._int_field(result_payload.get("l"), lines)
                result_payload = None

            if not terminal and not warning:
                warning = f"D1: límite de {wire_guard} continuaciones WS alcanzado."

            if audit_enabled():
                from tester_spin.provider_return_checks import d1_check
                money = {'balance_before': result_payload['b'], 'base_cost': init_payload['b1']} if ante_cost is not None and terminal else {}
                proof = d1_check(self, ws, frames, lines, bet_index, result_payload.get('st') if result_payload else None, attempt_dir, timeout_s, initial_terminal=self._d1_result_terminal(result_payload), **money) if terminal else pending_return(attempt_dir, 'Estado D1 no resuelto')
                if proof['status'] != 'CONFIRMED':
                    warning = (warning+' Regreso al juego base pendiente: '+proof['status']).strip()
                    terminal = False
            elapsed_ms = (time.monotonic() - started) * 1000.0
            artifact = {
                "spec": spec,
                "terminal": terminal,
                "wire_steps": steps,
                "operation": feature_kind if feature_selector is not None else "SPIN",
                "purchase_accepted": purchase_accepted if feature_selector is not None and feature_kind == "PURCHASE" else None,
                "antebet_accepted": terminal if feature_selector is not None and feature_kind == "ANTE_BET" else None,
                "warning": warning,
                "frames": frames,
                "final_result": result_payload,
            }
            (attempt_dir / "ws-attempt.json").write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True, terminal, elapsed_ms, str(spec["ws_url"]), frames, warning
        finally:
            try:
                close_wire = self._wire_message("3", "close")
                ws.send(close_wire)
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass

    def _observe_game_websockets(
        self,
        entry_url: str,
        *,
        timeout_s: float,
        attempt_dir: Path,
    ) -> tuple[list[str], list[dict[str, object]], str]:
        sockets: list[str] = []
        frames: list[dict[str, object]] = []
        error = ""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                def on_websocket(ws) -> None:
                    url = str(ws.url)
                    noise_url = self._is_noise_websocket_url(url)
                    if not noise_url and url not in sockets:
                        sockets.append(url)

                    def capture(direction: str):
                        def handler(payload) -> None:
                            if len(frames) >= 300:
                                return
                            decoded = self._decode_ws_json(payload)
                            telemetry = noise_url or self._is_webvisor_payload(decoded)
                            shape = classify_spin_message(self._decode_ws_json(payload)) if direction == "sent" else None
                            frames.append(
                                {
                                    "direction": direction,
                                    "spin_shape": shape,
                                    "websocket_url": url,
                                    "classification": (
                                        "telemetry_ignored"
                                        if telemetry
                                        else "provider_or_unknown"
                                    ),
                                    "payload": self._frame_preview(payload),
                                }
                            )
                        return handler

                    ws.on("framesent", capture("sent"))
                    ws.on("framereceived", capture("received"))

                page.on("websocket", on_websocket)
                page.goto(
                    entry_url,
                    wait_until="domcontentloaded",
                    timeout=max(1_000, int(timeout_s * 1000)),
                )
                page.wait_for_timeout(int(min(max(timeout_s, 2.0), 10.0) * 1000))
                context.close()
                browser.close()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        (attempt_dir / "runtime-websocket.json").write_text(
            json.dumps(
                {
                    "entry_url": entry_url,
                    "transport": "websocket",
                    "websocket_urls": sockets,
                    "frames": frames,
                    "error": error,
                    "note": (
                        "Passive runtime observation only. The public catalogue is "
                        "Webflow HTML, while game protocol discovery remains WebSocket."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return sockets, frames, error

    def test_game(
        self,
        game: Game,
        *,
        spins: int,
        timeout_s: float,
        stop_event: threading.Event,
        progress: Progress,
    ) -> GameTestResult:
        repetitions = max(1, int(spins))
        started_iso = utc_now_iso()
        started = time.monotonic()
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = self.game_dir(game) / "tests" / f"{stamp}-1spin4win-direct-ws"
        attempts: list[SpinAttempt] = []
        successes = 0
        responded = 0
        errors: list[str] = []
        resolved_symbol = game.symbol
        purchase_modes: list[dict[str, Any]] = []
        feature_domains: dict[str, Any] = {}

        progress(
            f"[{game.name}] D1: ejecutando {repetitions} tirada(s) directamente "
            "contra el WebSocket del cliente oficial."
        )

        jobs = [("SPIN", None)] * repetitions
        purchases_added = False
        mode_kinds = {"SPIN":"SPIN"}
        for number, (mode_id, selector) in enumerate(jobs, 1):
            mode_kind = mode_kinds.get(mode_id,"PURCHASE" if selector is not None else "SPIN")
            if stop_event.is_set() or audit_blocked():
                break
            attempt_dir = run_dir / f"attempt-{number:03d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            try:
                ok, terminal, elapsed_ms, endpoint, frames, warning = (
                    self._execute_direct_ws_spin(
                        game,
                        timeout_s=timeout_s,
                        attempt_dir=attempt_dir,
                        **({"feature_selector": selector} if selector is not None else {}),
                        **({"feature_kind":"ANTE_BET"} if mode_kind == "ANTE_BET" else {}),
                    )
                )
                responded += int(ok)
                successes += int(ok and terminal)

                try:
                    spec = json.loads(
                        (attempt_dir / "runtime-spec.json").read_text(encoding="utf-8")
                    )
                    resolved_symbol = str(spec.get("game_name") or resolved_symbol)
                    if not purchases_added and mode_id == 'SPIN':
                        feature_domains = spec.get('feature_domains', {})
                        purchase_modes.extend(spec.get("purchase_modes") or [])
                        purchase_modes.extend(spec.get("antebet_modes") or [])
                        for mode in purchase_modes:
                            mode_kinds[mode["id"]] = mode.get("kind","PURCHASE")
                            if mode.get('executable') and mode.get('feature_selector') is not None:
                                jobs.extend([(mode['id'], mode['feature_selector'])] * repetitions)
                        purchases_added = True
                except Exception:
                    pass

                attempts.append(
                    SpinAttempt(
                        number=number,
                        ok=ok,
                        mode_id=mode_id,
                        mode_kind=mode_kind,
                        elapsed_ms=elapsed_ms,
                        symbol=resolved_symbol,
                        endpoint=endpoint,
                        terminal=terminal,
                        wire_steps=sum(
                            1
                            for frame in frames
                            if frame.get("direction") == "sent"
                            and frame.get("classification") in {"spin", "purchase", "antebet", "continuation"}
                        ),
                        warning=warning,
                        artifact_dir=str(attempt_dir),
                    )
                )
                progress(
                    f"[{game.name}] {mode_id} {number}/{len(jobs)}: "
                    f"{'OK' if terminal else 'PARCIAL'} {elapsed_ms:.0f} ms, "
                    f"frames={len(frames)}"
                    + (f"; {warning}" if warning else "")
                )
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                errors.append(message)
                attempts.append(
                    SpinAttempt(
                        number=number,
                        ok=False,
                        mode_id=mode_id,
                        mode_kind=mode_kind,
                        symbol=resolved_symbol,
                        terminal=False,
                        error=message,
                        artifact_dir=str(attempt_dir),
                    )
                )
                progress(f"[{game.name}] {mode_id} {number}/{len(jobs)}: ERROR {message}")

        elapsed_total = (time.monotonic() - started) * 1000.0
        attempted = len(attempts)
        if attempted and successes == attempted:
            status = "OK"
            error = ""
        elif responded:
            status = "PARCIAL"
            error = (
                f"D1 respondió {responded}/{attempted}; "
                f"tiradas terminales={successes}/{attempted}."
            )
        else:
            status = "ERROR"
            error = errors[0] if errors else "No se completó ninguna tirada D1."

        result = GameTestResult(
            provider=self.key,
            slug=game.slug,
            game_name=game.name,
            game_url=game.url,
            requested_spins=len(jobs),
            successful_spins=successes,
            failed_spins=sum(1 for attempt in attempts if not attempt.ok),
            status=status,
            symbol=resolved_symbol,
            discovered_modes=[
                {
                    "id": "SPIN",
                    "kind": "SPIN",
                    "transport": "websocket",
                    "catalog_transport": "webflow_html",
                    "automated": True,
                    "spin_validated": any(attempt.mode_kind == "SPIN" and attempt.ok and attempt.terminal and not attempt.warning for attempt in attempts),
                    "wire_prefix": "A/u2",
                    "init_type": "0",
                    "spin_type": "1",
                    "result_type": 3,
                }
            ],
            started_at=started_iso,
            finished_at=utc_now_iso(),
            elapsed_ms=elapsed_total,
            error=error,
            run_dir=str(run_dir),
            attempts=attempts,
            feature_domains=feature_domains,
        )
        for mode in purchase_modes:
            completed = sum(1 for attempt in attempts if attempt.mode_id == mode['id'] and attempt.ok and attempt.terminal and not attempt.warning)
            mode['validated'] = completed >= repetitions
            mode['covered_options'] = [mode['id']] if mode['validated'] else []
        apply_purchase_coverage(result, purchase_modes)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result
