"""Public 3 Oaks catalog and JSON launcher, without evaluating JavaScript."""
import json
import re
from urllib.parse import urljoin, urlparse

from tester_spin.models import Game

ORIGIN = "https://3oaks.com"
CATALOG_API = ORIGIN + "/api/v1/games"
SLUG = re.compile(r"[a-z0-9_]+\Z")


def games_from_page(payload: dict) -> list[Game]:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("3 Oaks: página de catálogo inválida")
    games = []
    for row in data["items"]:
        if not isinstance(row, dict):
            raise ValueError("3 Oaks: fila de catálogo inválida")
        if row.get("has_page") is not True:
            continue
        slug = str(row.get("name") or "")
        title = str(row.get("title_text") or "").strip()
        if not SLUG.fullmatch(slug) or not title:
            raise ValueError("3 Oaks: nombre o slug inválido")
        image = str(row.get("main_logo_file") or row.get("icon_file") or "")
        games.append(Game("3oaks", slug, title, ORIGIN + "/game/" + slug,
                          thumbnail_url=urljoin(ORIGIN, image) if image else "", symbol=slug))
    return games


def launcher_config(html: str) -> dict:
    match = re.search(r"\}\)\(window,\s*", html)
    if not match:
        raise ValueError("3 Oaks: configuración del launcher no observada")
    try:
        config, _ = json.JSONDecoder().raw_decode(html[match.end():])
    except (ValueError, TypeError) as exc:
        raise ValueError("3 Oaks: launcher sin configuración JSON") from exc
    if not isinstance(config, dict) or not isinstance(config.get("options"), dict):
        raise ValueError("3 Oaks: configuración inválida")
    return config


def client_family(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname != "static.3oaks.com":
        return "unknown"
    match = re.search(r"/clients_([a-z]+)/", parsed.path)
    return match.group(1) if match else "unknown"


def family_map(config: dict) -> dict[str, str]:
    return {str(row["name"]): client_family(str(row.get("client_url") or ""))
            for row in config.get("available_games", [])
            if isinstance(row, dict) and SLUG.fullmatch(str(row.get("name") or ""))}
