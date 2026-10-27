"""Read official public catalog structures; never execute scripts or infer modes."""
import html,json,re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin,urlsplit,unquote,quote
from xml.etree import ElementTree
from bs4 import BeautifulSoup
from .sources import SOURCES

def walk(value):
 if isinstance(value,dict):
  yield value
  for item in value.values():yield from walk(item)
 elif isinstance(value,list):
  for item in value:yield from walk(item)

def flight_objects(text):
 for match in re.finditer(r'self\.__next_f\.push\(',text):
  try:arr,_=json.JSONDecoder().raw_decode(text[match.end():]);body=arr[1]
  except (ValueError,IndexError):continue
  if not isinstance(body,str):continue
  for line in body.splitlines():
   payload=line.partition(':')[2]
   if payload.startswith(('[','{')):
    try:yield json.loads(payload)
    except ValueError:continue

def row(name,url,symbol='',thumbnail='',studio='',category=''):
 slug=urlsplit(url).path.rstrip('/').rsplit('/',1)[-1].removesuffix('.html')
 return {'name':html.unescape(name).strip(),'slug':slug,'url':url,'symbol':str(symbol or ''),'thumbnail_url':thumbnail,'studio':studio,'category':category}

def parse_html(key,text):
 spec=SOURCES[key];soup=BeautifulSoup(text,'html.parser');rows=[]
 if spec['kind']=='amusnet':
  for obj in flight_objects(text):
   for game in walk(obj):
    if 'gin' in game and isinstance(game.get('path'),str) and game.get('title'):
     rows.append(row(game['title'],urljoin(spec.get('feed',spec['url']),game['path']),game['gin'],(game.get('thumbnail') or {}).get('url','')))
 elif spec['kind']=='greentube':
  for match in re.finditer(r'\[\s*\{\s*"ID"\s*:',text):
   try:games,_=json.JSONDecoder().raw_decode(text[match.start():])
   except ValueError:continue
   for game in games:
    if game.get('permalink') and game.get('title'):rows.append(row(game['title'],game['permalink'],game.get('ID'),game.get('thumbnail','') if isinstance(game.get('thumbnail'),str) else ''))
 elif spec['kind']=='global':
  script=soup.select_one('#__NEXT_DATA__')
  if script:
   data=json.loads(script.string)['props']['pageProps']['pageData']
   identities={}
   for group in data.get('productType',[]):
    for game in group.get('games',[]):
     if game.get('gameid') and game.get('gamename'):
      # The public Products listing is the authority; don't invent detail/demo routes.
      item=row(game['gamename'],spec['url'],game['gameid'],studio=game.get('description',''),category=group.get('productname',''))
      item['slug']=str(game['gameid']).casefold()
      if item['slug'] in identities:
       identities[item['slug']].setdefault('catalog_aliases',[]).append(item['name'])
      else:identities[item['slug']]=item
   rows=list(identities.values())
 else:
  pattern=spec.get('pattern',r'^/games/[^/]+/?$')
  canonical_links={urljoin(spec['url'],a['href']) for a in soup.select('a[href]')
                   if not urlsplit(urljoin(spec['url'],a['href'])).fragment}
  for a in soup.select('a[href]'):
   url=urljoin(spec['url'],a['href'])
   if key=='playson' and urlsplit(url).fragment=='autoplay' and url.partition('#')[0] in canonical_links:continue
   if not re.fullmatch(pattern,urlsplit(url).path):continue
   img=a.find('img');name=a.get('aria-label') or a.get('title') or (img.get('alt') if img else '') or a.get_text(' ',strip=True)
   if name.casefold() in ('play demo','demo'):continue
   if name in ('Info','More Info','Play','View Game',''):  # find real card heading, not a control label
    parent=a.parent
    for _ in range(3):
     heading=parent.find(re.compile(r'^h[1-6]$'))
     if heading:name=heading.get_text(' ',strip=True);break
     parent=parent.parent or parent
   if not name or name in ('Info','More Info','Play','View Game'):name=unquote(urlsplit(url).path.rstrip('/').rsplit('/',1)[-1]).removesuffix('.html').replace('-',' ').title()
   rows.append(row(name,url,thumbnail=urljoin(url,(img.get('src') or img.get('data-src') or '')) if img else ''))
 return rows

def playtech_slot_rows(data,feed):
 """Use official Slots membership; a demo engine is not a game category."""
 groups=[c for c in feed.get('gamesFeedCategories',[]) if c.get('seoFriendlyCategoryName')=='slots']
 if len(groups)!=1:raise ValueError('Categoría oficial Slots ausente o ambigua')
 config=groups[0].get('desktopCategoryConfiguration',{})
 codes=config.get('categoryGames')
 if config.get('isActive') is not True or not isinstance(codes,list) or not codes or any(not isinstance(c,str) or not c for c in codes):
  raise ValueError('Categoría oficial Slots incompleta')
 slots=set(codes);rows=[];spec=SOURCES['playtech']
 demo_types={t['name'] for t in data['gameTypes'] if t.get('demoPlayUrl')}
 for game in data['games'].values():
  if game.get('gameCode') not in slots or game.get('desktopGameType') not in demo_types:continue
  item=row(game['name'],spec['url'],game['gameCode'],urljoin(spec['url'],game.get('defaultGameImage','')),category=game.get('desktopGameType',''))
  item.update(slug='game-'+quote(str(game['gameCode']),safe=''),demo_availability=game.get('demoModeSupport','unknown'),game_kind='slot',classification_source=spec['url']+'initialResources/gamesFeeds/'+quote(feed.get('name','casino-2026'),safe=''),classification_category='slots')
  rows.append(item)
 if not rows:raise ValueError('La categoría Slots no produjo juegos demo verificables')
 return rows

def fetch_rows(key,http,stop_event,max_pages=100):
 spec=SOURCES[key];kind=spec['kind'];rows=[];max_pages=max_pages or 1000
 def get(url,**kwargs):
  if stop_event.is_set():raise InterruptedError('Catálogo cancelado')
  response=http.get(url,timeout=25,**kwargs);response.raise_for_status();return response
 if kind=='netent':
  # Public browser CMS credential is read from the current official client,
  # never persisted in a catalog or duplicated as a source constant.
  client=get(spec['url']).content.decode('utf-8')
  scripts=[urljoin(spec['url'],s['src']) for s in BeautifulSoup(client,'html.parser').select('script[src]') if s['src'].startswith('/_next/static/chunks/')]
  token=None
  def read_script(url):return get(url).content.decode('utf-8')
  for offset in range(0,len(scripts),6):
   with ThreadPoolExecutor(max_workers=6) as pool:
    for script in pool.map(read_script,scripts[offset:offset+6]):
     match=re.search(r'baseUrl:"https://cmsevo.com/api",prepareHeaders:[a-z]=>\{let [a-z]="([a-f0-9]{64,512})"',script)
     if match:token=match[1]
   if token:break
  if not token:raise ValueError('Contrato público del CMS no reconocido')
  http.headers['Authorization']='Bearer '+token
  studios=get('https://cmsevo.com/api/studios').json()['data']
  identities=[s['id'] for s in studios if s.get('attributes',{}).get('title','').casefold()=='netent']
  if len(identities)!=1:raise ValueError('Identidad del estudio NetEnt no verificable')
  for page in range(1,max_pages+1):
   data=get('https://cmsevo.com/api/games',params={'filters[studio][$eq]':identities[0],'pagination[pageSize]':100,'pagination[page]':page,'populate':'deep'}).json()
   for game in data['data']:
    attrs=game['attributes'];studio=(attrs.get('studio') or {}).get('data') or {}
    if studio.get('id')!=identities[0]:raise ValueError('CMS devuelve un juego de otro estudio')
    if attrs.get('slug') and attrs.get('name'):
     image=(attrs.get('icon') or {}).get('data') or {}
     rows.append(row(attrs['name'],urljoin(spec['url']+'/',attrs['slug']),attrs.get('tableId') or game['id'],image.get('attributes',{}).get('url',''),studio='NetEnt'))
   if page>=data.get('meta',{}).get('pagination',{}).get('pageCount',1):break
 elif kind=='playngo':
  offset=0;seen=set()
  for _ in range(max_pages):
   data=get('https://www.playngo.com/api/games',params={'offset':offset,'sort':'date-desc'}).json()
   for game in data['games']:rows.append(row(game['title'],urljoin(spec['url']+'/',game['slug']),game['sku'],game.get('thumbnailUrl','')))
   next_offset=data.get('nextOffset')
   if next_offset is None:break
   if not isinstance(next_offset,int) or next_offset<=offset or next_offset in seen:raise ValueError('Paginación repetida de Play’n GO')
   seen.add(next_offset);offset=next_offset
 elif kind=='pgsoft':
  data=get('https://api.pgsoft.com/Game/GetDefaultAllGame/language/en-US').json()
  for game in data['dt']['dagl']:
   rows.append(row(game['gn'],urljoin(spec['url'],'../'+str(game['gid'])+'/'),game['pgid']))
 elif kind=='playtech':
  from playwright.sync_api import sync_playwright
  with sync_playwright() as playwright:
   browser=playwright.chromium.launch(headless=True)
   try:
    page=browser.new_page();page.goto(spec['url'],wait_until='domcontentloaded',timeout=45000)
    page.wait_for_function('typeof window.Playtech?.API?.game?.getGamesConfiguration === "function"',timeout=45000)
    data=page.evaluate('async () => await Playtech.API.game.getGamesConfiguration()')
    feed=page.evaluate('async () => await Playtech.API.game.getGamesFeed("casino-2026")')
   finally:browser.close()
  rows=playtech_slot_rows(data,feed)
 elif kind=='sitemap':
  root=ElementTree.fromstring(get(spec['feed']).content)
  for element in root.iter():
   if element.tag.rsplit('}',1)[-1]=='loc' and element.text and re.fullmatch(spec['pattern'],urlsplit(element.text).path):
    rows.append(row(unquote(urlsplit(element.text).path.rstrip('/').rsplit('/',1)[-1]).replace('-',' ').title(),element.text))
 elif kind=='blueprint':
  text=get(spec['url']).content.decode('utf-8');soup=BeautifulSoup(text,'html.parser');form=soup.select_one('#game-search-form')
  if not form:raise ValueError('Formulario oficial Blueprint ausente')
  values={x['name']:x.get('value','') for x in form.select('input[name]') if x.get('type')!='checkbox' or x.has_attr('checked')}
  response=http.post('https://blueprintgaming.com/games-list',data=values,headers={'X-Requested-With':'XMLHttpRequest','Referer':spec['url']},timeout=25);response.raise_for_status()
  rows=parse_html(key,response.content.decode('utf-8'))
 else:rows=parse_html(key,get(spec.get('feed',spec['url'])).content.decode('utf-8'))
 return rows
