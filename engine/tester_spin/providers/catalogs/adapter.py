"""Catalog-only adapters. Protocol support remains explicitly pending."""
import json,re
from pathlib import Path
from urllib.parse import urlsplit
from curl_cffi import requests
from tester_spin.models import Game,GameTestResult,utc_now_iso
from tester_spin.providers.base import ProviderAdapter
from .sources import SOURCES
from .fetch import fetch_rows

def validate_rows(key,rows):
 if not isinstance(rows,list):raise ValueError('Catálogo inválido')
 found={};hosts=SOURCES[key]['hosts']
 for row in rows:
  if not isinstance(row,dict):raise ValueError('Fila de catálogo inválida')
  slug=row.get('slug');name=row.get('name');url=row.get('url');parsed=urlsplit(url or '')
  if not isinstance(slug,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.'%+~-]{0,199}",slug):raise ValueError('Identidad de catálogo inválida')
  if slug.endswith('.') or re.fullmatch(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',slug):raise ValueError('Identidad reservada de Windows')
  if not isinstance(name,str) or not name.strip():raise ValueError('Nombre ausente')
  if parsed.scheme!='https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None,443):raise ValueError('Enlace fuera de la autoridad del catálogo')
  if slug in found and found[slug]['name']!=name:raise ValueError('Identidad duplicada con distinto nombre')
  found[slug]=row
 return list(found.values())

class CatalogProvider(ProviderAdapter):
 execution_supported=False
 max_test_concurrency=1
 def __init__(self,data_root):
  self.provider_root=Path(data_root)/'providers'/self.key;self.provider_root.mkdir(parents=True,exist_ok=True)
  self.http=requests.Session(impersonate='chrome')
  self.set_catalog_authority(False,'Catálogo público: sin autoridad de eliminación ni protocolo aprendido')
 def fetch_live_rows(self,stop_event,max_pages):return fetch_rows(self.key,self.http,stop_event,max_pages)
 def game_dir(self,game):
  validate_rows(self.key,[{'slug':game.slug,'name':game.name,'url':game.url}])
  if game.provider!=self.key:raise ValueError('Proveedor incorrecto')
  folder=self.provider_root/game.slug;folder.mkdir(exist_ok=True);return folder
 def har_artifact_dir(self,game):
  folder=self.game_dir(game)/'analysis';folder.mkdir(exist_ok=True);return folder
 def crawl_catalog(self,*,stop_event,progress,max_pages=100,on_game=None):
  if stop_event.is_set():return []
  snapshot=Path(__file__).with_name('snapshots')/(self.key+'.json')
  saved=json.loads(snapshot.read_text(encoding='utf-8')) if snapshot.exists() else {'games':[],'coverage':'pending'}
  rows={r['slug']:r for r in validate_rows(self.key,saved['games']) if self.key!='playtech' or r.get('game_kind')=='slot'};source='snapshot oficial incluido'
  self.set_catalog_authority(False,'Snapshot de respaldo: sin eliminación automática')
  try:
   live=validate_rows(self.key,self.fetch_live_rows(stop_event,max_pages))
   if not live:raise ValueError('La fuente no devolvió juegos verificables')
   if self.key=='playtech':
    if any(r.get('game_kind')!='slot' or r.get('classification_category')!='slots' for r in live):raise ValueError('Clasificación Slots ausente')
    rows={r['slug']:r for r in live}
    self.set_catalog_authority(True,'Categoría oficial Slots completa')
   else:rows.update({r['slug']:r for r in live})
   source=SOURCES[self.key].get('feed',self.catalog_url)
  except InterruptedError:return []
  except Exception as exc:progress(f'{self.display_name}: se conserva el catálogo guardado ({type(exc).__name__}).')
  if not rows:raise RuntimeError(f'{self.display_name}: fuente pública pendiente; no se declara catálogo completo ni se eliminan datos.')
  found=[]
  for r in sorted(rows.values(),key=lambda r:r['name'].casefold()):
   if stop_event.is_set():break
   game=Game(self.key,r['slug'],r['name'],r['url'],symbol=r.get('symbol',''),thumbnail_url=r.get('thumbnail_url',''))
   path=self.game_dir(game)/'game.json'
   try:metadata=json.loads(path.read_text(encoding='utf-8'))
   except (OSError,ValueError):metadata={}
   # A listing without a runtime ID does not invalidate an identity previously
   # resolved for this exact game. Keep its original launch provenance intact.
   if (not game.symbol and metadata.get('provider')==self.key and metadata.get('slug')==game.slug
       and isinstance(metadata.get('symbol'),str) and metadata['symbol'].strip()):
    game.symbol=metadata['symbol']
   metadata.update(provider=self.key,slug=game.slug,name=game.name,symbol=game.symbol,public_url=game.url,catalog_source=source,
     game_kind=r.get('game_kind','unknown'),classification_source=r.get('classification_source',''),classification_category=r.get('classification_category',''),studio=r.get('studio',''),category=r.get('category',''),demo_availability=r.get('demo_availability','unknown'),catalog_aliases=r.get('catalog_aliases',[]),catalog_coverage=saved.get('coverage','public_listing'),execution_supported=self.execution_supported,catalog_updated_at=utc_now_iso())
   path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
   found.append(game)
   if on_game:on_game(game)
  progress(f'{self.display_name}: {len(found)} juegos; '+('ejecutor disponible para contratos reconocidos.' if self.execution_supported else 'ejecutor pendiente de protocolo.'))
  return found
 def test_game(self,game,*,spins,timeout_s,stop_event,progress):
  result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,spins,'PARCIAL',symbol=game.symbol)
  result.error='Catálogo disponible; falta aprender y verificar el protocolo de ejecución del proveedor.'
  result.feature_domains={key:{'declaration_state':'UNKNOWN','options':[]} for key in ('purchase','antebet')}
  if self.key=='playtech':
   evidence=self.har_artifact_dir(game)/'protocol-evidence.json'
   if evidence.is_file():
    from tester_spin.providers.playtech.protocol import inspect_evidence
    try:
     learned=inspect_evidence(json.loads(evidence.read_text(encoding='utf-8')),game.symbol)
     result.structural_map['playtech_protocol']=learned
     result.feature_domains=learned['feature_domains']
     result.error=f"GPAS: {len(learned['effective_modes'])} modalidades declaradas, {len(learned['contexts'])} contextos de apuesta; falta verificar ejecución y cobertura de ramas en sesión nueva."
    except (ValueError,TypeError,OSError) as exc:
     result.error='Evidencia Playtech no válida para este juego: '+str(exc)
  progress(result.error);return result

for key,spec in SOURCES.items():
 globals()[spec['class']]=type(spec['class'],(CatalogProvider,),{'key':key,'display_name':spec['name'],'catalog_url':spec['url'],'__module__':__name__})
