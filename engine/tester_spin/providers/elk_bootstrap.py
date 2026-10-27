"""Fail-closed binding of an official ELK detail page to its public demo.

The observed site has stale data-src values.  Its verified click handler and
lightGallery loader both select href.  This profile deliberately recognizes
that complete handler, rather than treating any launcher-shaped URL as proof.
No title-to-ID table, script execution, or game request is involved.
"""
import hashlib
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup


PROFILE = 'elk.official-lightbox-href/v1'
SCRIPT_PATH = '/app/themes/elkstudios/assets/dist/app.min.js'
# Exact public client primitive observed in Actions 40551803690.  A changed
# handler is unsupported until its selection semantics have been reviewed.
_HANDLER = ('.on("click",".lightbox-iframe",function(a){'
    'if(navigator.userAgent.indexOf("Safari")!=-1&&navigator.userAgent.indexOf("Chrome")==-1)'
    'd.body.bind("touchend click",".lightbox-iframe",function(a){'
    'var b=c(this).prop("href"),d=c(this).prop("target");'
    'b&&("_blank"==d?window.open(b,d):window.location=b)});'
    'else{var b=c(this).prop("href");c(this).data("src",b)}})')
_LOADER = re.compile(r'(?P<items>[A-Za-z_$][\w$]*\.\$items)\.eq\((?P<index>[A-Za-z_$][\w$]*)\)'
    r'\.attr\("href"\)\|\|(?P=items)\.eq\((?P=index)\)\.attr\("data-src"\)')


def _reject():
    raise ValueError('PUBLIC_DEMO_IDENTITY_NOT_CONFIRMED')


def _authority(url, host):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != host or
                parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment):
            _reject()
        return parsed
    except (TypeError, ValueError):
        _reject()


def _page(game, page_url, html):
    parsed = _authority(page_url, 'www.elk-studios.com')
    if (game.provider != 'elk' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', game.slug)
            or page_url != game.url or parsed.path != '/games/' + game.slug + '/'
            or parsed.query or not isinstance(html, str) or len(html) > 4 * 1024 * 1024):
        _reject()
    soup = BeautifulSoup(html, 'html.parser')
    canonical = soup.select('link[rel="canonical"]')
    if len(canonical) != 1 or canonical[0].get('href') != page_url:
        _reject()
    title = lambda text: ' '.join(text.split()).casefold()
    headings = [h for h in soup.find_all('h1') if title(h.get_text(' ', strip=True)) == title(game.name)]
    if len(headings) != 1:
        _reject()
    panel = headings[0].find_parent(class_='entry-content')
    if panel is None:
        _reject()
    links = panel.select('a.lightbox-iframe[data-iframe="true"][href]')
    if not links or len({link['href'] for link in links}) != 1:
        _reject()
    return soup, links[0]


def official_script_url(game, page_url, html):
    """Validate page identity before allowing a request for its site script."""
    soup, _ = _page(game, page_url, html)
    scripts = soup.select('script#app-js[src]')
    if len(scripts) != 1:
        _reject()
    url = urljoin(page_url, scripts[0]['src'])
    parsed = _authority(url, 'www.elk-studios.com')
    query = parse_qs(parsed.query, keep_blank_values=True)
    if parsed.path != SCRIPT_PATH or (query and
            (set(query) != {'ver'} or len(query['ver']) != 1 or not re.fullmatch(r'\d+(?:\.\d+)*', query['ver'][0]))):
        _reject()
    return url


def extract_official_demo(game, page_url, html, script_url, script_source):
    declared_script = official_script_url(game, page_url, html)
    if script_url != declared_script or not isinstance(script_source, str) or len(script_source) > 2 * 1024 * 1024:
        _reject()
    if (script_source.count('.on("click",".lightbox-iframe",') != 1 or
            script_source.count(_HANDLER) != 1 or not _LOADER.search(script_source)):
        raise ValueError('OFFICIAL_DEMO_LINK_HANDLER_UNRECOGNIZED')
    _, link = _page(game, page_url, html)
    launch = link['href']
    parsed = _authority(launch, 'gamelauncher-stage.contentmedia.eu')
    query = parse_qs(parsed.query, keep_blank_values=True)
    ids = query.get('gameid', [])
    if (parsed.path != '/1.0/game/' or len(ids) != 1 or not re.fullmatch(r'\d+', ids[0])
            or query.get('mode') != ['demo'] or query.get('operatorid') != ['44']
            or (game.symbol and game.symbol != ids[0])):
        _reject()
    return {'symbol': ids[0], 'client_url': launch, 'launch_evidence': {
        'profile': PROFILE, 'source': page_url, 'script_url': script_url,
        'page_sha256': hashlib.sha256(html.encode('utf-8')).hexdigest(),
        'script_sha256': hashlib.sha256(script_source.encode('utf-8')).hexdigest(),
        'selected_attribute': 'href', 'data_src_conflicts': link.get('data-src', launch) != launch}}
