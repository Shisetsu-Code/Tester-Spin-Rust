"""Official numeric IDs avoid changing slugs when a title or encoded URL changes."""
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from tester_spin.models import Game

ORIGIN = "https://www.hacksawgaming.com"
CATALOG_URL = ORIGIN + "/games/slots"
GAME_ID = re.compile(r"[1-9][0-9]{0,9}\Z")


def games_from_rows(rows):
    games, seen = [], set()
    for row in rows:
        identifier = str(row.get("id") or "")
        name = str(row.get("title") or "").split(" | casino game image")[0].strip()
        if not GAME_ID.fullmatch(identifier) or not name or identifier in seen:
            raise ValueError("Hacksaw: catálogo inválido o ID duplicado")
        seen.add(identifier)
        url = row.get("url") or CATALOG_URL + "#game-" + identifier
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "www.hacksawgaming.com" or not parsed.path.startswith("/games/"):
            raise ValueError("Hacksaw: URL de catálogo inválida")
        thumbnail = str(row.get("thumbnail") or "")
        image = urlsplit(thumbnail)
        if thumbnail and (image.scheme != "https" or image.hostname != "www-live.hacksawgaming.com"
                          or image.path != "/casino_thumbnails/" + identifier + ".jpg"):
            raise ValueError("Hacksaw: miniatura no corresponde al ID")
        games.append(Game("hacksaw", identifier, name, url, thumbnail_url=thumbnail, symbol=identifier))
    return games


def games_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for card in soup.select('li.GridListItem[data-gameid]'):
        link, image = card.select_one('a[href]'), card.select_one('[data-bg-image]')
        rows.append({"id": card["data-gameid"], "title": card.get("aria-label"),
                     "url": urljoin(ORIGIN, link["href"]) if link else None,
                     "thumbnail": image.get("data-bg-image") if image else ""})
    if not rows:
        raise ValueError("Hacksaw: catálogo vacío")
    return games_from_rows(rows)
