"""Published WordPress game catalog, verified against its advertised REST route."""
import json,re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from tester_spin.models import Game
from .browser_catalog import RubyPlayBrowserCatalogClient


def parse_page(response):
    if response.get('status')!=200:raise ValueError('RubyPlay REST: HTTP no exitoso')
    try:total=int(response['total']);pages=int(response['pages'])
    except (KeyError,TypeError,ValueError):raise ValueError('RubyPlay REST: totales ausentes') from None
    rows=response.get('data')
    if total<1 or not 1<=pages<=1000 or not isinstance(rows,list) or not rows:
        raise ValueError('RubyPlay REST: dominio vacío o inválido')
    games=[];ids=set();slugs=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('RubyPlay REST: fila inválida')
        identity=row.get('id');slug=row.get('slug');url=row.get('link');parsed=urlsplit(url or '')
        title=row.get('title');title=title.get('rendered') if isinstance(title,dict) else None
        if (type(identity) is not int or identity<=0 or identity in ids or not isinstance(slug,str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]*',slug) or slug in slugs
                or parsed.scheme!='https' or parsed.hostname not in {'rubyplay.com','www.rubyplay.com'}
                or parsed.username or parsed.password or parsed.port not in {None,443}
                or parsed.path.rstrip('/')!='/games/'+slug or not isinstance(title,str)):
            raise ValueError('RubyPlay REST: identidad, título o autoridad inválidos')
        name=BeautifulSoup(title,'html.parser').get_text(' ',strip=True)
        if not name:raise ValueError('RubyPlay REST: nombre vacío')
        ids.add(identity);slugs.add(slug);games.append(Game('rubyplay',slug,name,url))
    if len(games)>total:raise ValueError('RubyPlay REST: filas exceden total')
    return games,total,pages


def crawl(provider,*,stop_event,progress,max_pages,on_game):
    root=provider.provider_root/'catalog-pages/rest';root.mkdir(parents=True,exist_ok=True)
    client=RubyPlayBrowserCatalogClient(provider.catalog_url,timeout_s=30)
    games=[];seen=set();total=None;pages=None
    provider.set_catalog_authority(False,'REST crawl incompleto')
    try:
        client.start()
        if urlsplit(client._page.url).hostname not in {'rubyplay.com','www.rubyplay.com'}:
            raise ValueError('RubyPlay REST: navegador fuera de autoridad')
        index=client._page.evaluate("""async()=>{const r=await fetch('/wp-json/');const data=await r.json();return {status:r.status,route:data.routes?.['/wp/v2/games']||null};}""")
        (root/'route.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
        if index.get('status')!=200 or not isinstance(index.get('route'),dict):
            raise ValueError('RubyPlay REST: ruta games no anunciada')
        page=1
        while pages is None or page<=pages:
            if stop_event.is_set():raise InterruptedError('Catálogo detenido')
            if max_pages>0 and page>max_pages:raise ValueError('RubyPlay REST: paginación limitada')
            response=client._page.evaluate("""async(page)=>{const query=new URLSearchParams({per_page:'100',page:String(page),orderby:'id',order:'asc',_fields:'id,slug,link,title'});const r=await fetch('/wp-json/wp/v2/games?'+query);return {status:r.status,total:r.headers.get('X-WP-Total'),pages:r.headers.get('X-WP-TotalPages'),data:await r.json()};}""",page)
            (root/f'page-{page:03d}.json').write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')
            found,current_total,current_pages=parse_page(response)
            if total is not None and (current_total!=total or current_pages!=pages):raise ValueError('RubyPlay REST: totales cambiaron durante paginación')
            total,pages=current_total,current_pages
            if seen & {g.slug for g in found}:raise ValueError('RubyPlay REST: página repetida')
            seen.update(g.slug for g in found);games.extend(found)
            progress(f'RubyPlay REST página {page}/{pages}: {len(found)} juegos; acumulados={len(games)}/{total}.')
            page+=1
        if len(games)!=total:raise ValueError('RubyPlay REST: cantidad incompleta')
    finally:client.close()
    from .catalog import RubyPlayCatalogRecord
    for game in games:
        provider._persist_game_catalog_metadata(RubyPlayCatalogRecord(game=game))
        if on_game:on_game(game)
    provider.set_catalog_authority(True,'REST games publicado: total y paginación completos')
    return games
