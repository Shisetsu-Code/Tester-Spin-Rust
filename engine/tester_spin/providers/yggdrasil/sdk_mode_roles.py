"""Interpret a learned SDK menu constructor against the current Modes domain.
No game names, IDs or command aliases are used to assign roles.
"""
import re,json,hashlib
from decimal import Decimal,InvalidOperation
CONSTRUCTOR=re.compile(r'createBettingModes\((\w+)\)\{let (\w+)=\[\];for\(const (\w+) in \1\)\2\.push\(\{command:"BASIC"===\3\?"":\3,type:"BASIC"===\3\?"BASIC":"BUY_BONUS",coinsPerBet:\1\[\3\]\.coinsPerBet\}\);return \2\}')
ID=re.compile(r'[A-Z][A-Z0-9_]{0,63}')
def _dynamic_roles(source,modes):
 if not isinstance(source,str) or not isinstance(modes,dict) or 'BASIC' not in modes or len(modes)>256:return None
 if len(CONSTRUCTOR.findall(source))!=1 or 'getBettingModesConfigsByType("BUY_BONUS")' not in source:return None
 prices={}
 try:
  for name,record in modes.items():
   if not isinstance(name,str) or not ID.fullmatch(name) or not isinstance(record,dict):return None
   value=record.get('coinsPerBet')
   if isinstance(value,bool):return None
   price=Decimal(str(value))
   if not price.is_finite() or price<=0 or price!=price.to_integral_value():return None
   prices[name]=str(price)
 except (InvalidOperation,ValueError,TypeError):return None
 raw=re.findall(r'GOLDEN_BET_IDS=(\[[^\]\n]{0,1024}\])',source)
 if 'GOLDEN_BET_IDS' in source and len(raw)!=1:return None
 try:golden=json.loads(raw[0]) if raw else []
 except ValueError:return None
 if not isinstance(golden,list) or not all(isinstance(v,str) and ID.fullmatch(v) and v!='BASIC' and v in modes for v in golden) or len(set(golden))!=len(golden):return None
 for name in golden:
  if '"'+name+'"!==e.type' not in source or not re.search(r'delete [A-Za-z_$][\w$]*\.originalData\.settings\.slotConfig\.Modes\.'+re.escape(name)+r'(?=[;,}])',source):return None
 roles={name:'SPIN' if name=='BASIC' else 'ANTE_BET' if name in golden else 'BUY_BONUS' for name in modes}
 tables=re.findall(r'gameBonusDescriptions=(\[\{id:.*?\}\])',source)
 if len(tables)>1:return None
 if tables:
  cards=re.findall(r'\{id:"([A-Z][A-Z0-9_]*)",descriptionKey:"([^"]+)"',tables[0])
  if not cards or len({name for name,_ in cards})!=len(cards) or {name for name,_ in cards}!={name for name,role in roles.items() if role=='BUY_BONUS'}:return None
 return {'profile':'sdk.dynamicModes/defaultBuy/excludedGolden/v1','roles':roles,'current_coins_per_bet':prices,'source_sha256':hashlib.sha256(source.encode()).hexdigest()}

def source_roles(source,modes):
 proof=_dynamic_roles(source,modes)
 if proof is not None:return proof
 from .card_menu_roles import source_roles as card_roles
 proof=card_roles(source,modes)
 if proof is not None:return proof
 from .single_card_roles import source_roles as single_card_roles
 return single_card_roles(source,modes)

def load_source(http,page_html,gameid,modes,directory,timeout):
 from urllib.parse import urlsplit,parse_qs,urljoin
 from bs4 import BeautifulSoup
 from pathlib import Path
 allowed={'staticdemo.yggdrasilgaming.com','staticpff.yggdrasilgaming.com'}
 urls=[]
 for element in BeautifulSoup(page_html,'html.parser').select('[data-iframe-src]'):
  url=element['data-iframe-src'];p=urlsplit(url);q=parse_qs(p.query)
  if p.scheme=='https' and p.hostname in allowed and [v.strip() for v in q.get('gameid',[])]==[gameid]:urls.append(url)
 if len(set(urls))!=1:return None
 try:
  response=http.get(urls[0],timeout=timeout)
  if response.status_code!=200 or len(response.text)>2000000:return None
  base=getattr(response,'url',urls[0]);p=urlsplit(base)
  if p.scheme!='https' or p.hostname not in allowed:return None
  scripts=[]
  for node in BeautifulSoup(response.text,'html.parser').select('script[src]'):
   url=urljoin(base,node['src']);p=urlsplit(url)
   if p.scheme=='https' and p.hostname in allowed and p.path.endswith('.js'):scripts.append(url)
  if not 1<=len(set(scripts))<=8:return None
  sources=[];manifest=[]
  for url in dict.fromkeys(scripts):
   response=http.get(url,timeout=timeout);p=urlsplit(getattr(response,'url',url))
   if response.status_code!=200 or p.scheme!='https' or p.hostname not in allowed or not p.path.endswith('.js') or len(response.text)>36000000:return None
   if sum(map(len,sources))+len(response.text)>64000000:return None
   sources.append(response.text);manifest.append({'host':p.hostname,'path':p.path,'sha256':hashlib.sha256(response.text.encode()).hexdigest()})
 except Exception:return None
 source='\n'.join(sources);proof=source_roles(source,modes)
 if proof is None:return None
 directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
 (directory/'sdk-mode-role-source.js').write_text(source,encoding='utf-8')
 (directory/'sdk-mode-role-proof.json').write_text(json.dumps({**proof,'assets':manifest},indent=2),encoding='utf-8')
 return source
