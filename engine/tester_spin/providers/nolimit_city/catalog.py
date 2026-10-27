"""Official affiliate demo identities; no inferred feature domains."""
import re
from urllib.parse import urlsplit
from tester_spin.models import Game

CATALOG_URL='https://nolimitcity.com/games'
FEED_URL='https://nolimitcity.com/json/games.json'
CODE=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,79}\Z')

def games_from_rows(rows):
    if not isinstance(rows,list):raise ValueError('Nolimit City: catálogo inválido')
    games=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Nolimit City: fila inválida')
        if row.get('studio')!='Nolimit City':continue
        code=row.get('code');name=row.get('name');url=row.get('url')
        if not isinstance(code,str) or not CODE.fullmatch(code) or code.casefold() in seen:
            raise ValueError('Nolimit City: identidad inválida o duplicada')
        if not isinstance(name,str) or not name.strip() or not isinstance(url,str):
            raise ValueError('Nolimit City: nombre o enlace ausente')
        parsed=urlsplit(url)
        if (parsed.scheme!='https' or parsed.netloc!='playin.com'
                or parsed.path!='/embed/v1/demo/'+code or parsed.query or parsed.fragment):
            raise ValueError('Nolimit City: enlace de demo no corresponde a su identidad')
        seen.add(code.casefold())
        games.append(Game('nolimit_city',code.casefold(),name.strip(),url,symbol=code))
    if not games:raise ValueError('Nolimit City: catálogo vacío o de otro estudio')
    return games
