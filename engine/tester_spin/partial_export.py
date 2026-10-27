"""Plain URL lists consumed by the manual Fuzzer TXT importer."""
from pathlib import Path
from urllib.parse import urlsplit


def game_urls(games, *, partial_only=False):
    urls=[];seen=set()
    for game in sorted(games,key=lambda g:(g.name.casefold(),g.slug)):
        if partial_only and str(game.display_status).strip().upper()!='PARCIAL':continue
        url=str(game.launch_url).strip();parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or any(c in url for c in ('\r','\n','\t')):
            raise ValueError('El juego '+game.name+' no tiene un enlace HTTPS válido para exportar.')
        if url not in seen:urls.append(url);seen.add(url)
    return urls


def write_partial_export(path,games):
    urls=partial_urls(games)
    Path(path).write_text(''.join(url+'\n' for url in urls),encoding='utf-8',newline='\n')
    return len(urls)


def partial_urls(games):
    return game_urls(games,partial_only=True)


def write_game_export(path,games):
    urls=game_urls(games)
    Path(path).write_text(''.join(url+'\n' for url in urls),encoding='utf-8',newline='\n')
    return len(urls)
