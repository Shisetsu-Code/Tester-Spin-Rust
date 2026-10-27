"""Learn confirmed purchase cards from SDK bindings, without executing JavaScript."""
import hashlib
import re
from decimal import Decimal, InvalidOperation

IDENT=r'[A-Za-z_$][\w$]*'
COMMAND=r'[A-Z][A-Z0-9_]{0,63}'

def source_roles(source,modes):
 if not isinstance(source,str) or not isinstance(modes,dict) or 'BASIC' not in modes:return None
 section='id:"buy-bonus-cards-section",eventName:"onBuyBonusCard",options:['
 if source.count(section)!=1:return None
 cards=source.split(section,1)[1].split(']}]',1)[0]
 card_ids=re.findall(r'\{id:"('+COMMAND+r')",active:!0,info:!0,value:',cards)
 if len(card_ids)!=2 or len(set(card_ids))!=2:return None
 dispatch=re.findall(r'if\(('+IDENT+r')==="BUY"\)('+IDENT+r')==="('+COMMAND+r')"\?this\.('+IDENT+r')\(('+IDENT+r')\):this\.('+IDENT+r')\(\5\);else',source)
 if len(dispatch)!=1 or dispatch[0][2]!=card_ids[0]:return None
 handlers=(dispatch[0][3],dispatch[0][5])
 if handlers[0]==handlers[1]:return None
 commands=[]
 for handler in handlers:
  matches=list(re.finditer(r'T\(this,"'+re.escape(handler)+r'",('+IDENT+r')=>\{const ('+IDENT+r')=async\(\)=>\{('+IDENT+r')\.gameState\.nextCommands=\["('+COMMAND+r')"\];',source))
  if len(matches)!=1:return None
  m=matches[0];body=source[m.end():m.end()+1400]
  end=body.find('});T(this,')
  if end>=0:body=body[:end]
  owner=m.group(3);callback=m.group(2)
  if 'this.bonusBought(!0)' not in body or 'await '+owner+'.gamePlay.start()' not in body or 'primaryButtonAction:'+callback+'})' not in body:return None
  commands.append(m.group(4))
 if len(set(commands))!=2 or set(modes)!={'BASIC',*commands}:return None
 markers=list(re.finditer(r'T\(this,"setupBets",\(\)=>\{',source))
 if len(markers)!=1:return None
 start=markers[0].end();setup=source[start:start+8000]
 end=setup.find('T(this,')
 if end>=0:setup=setup[:end]
 factors={}
 for index,command in enumerate(commands):
  bindings=re.findall(r'('+IDENT+r')=('+IDENT+r')\.gameState\.modes\.'+re.escape(command)+r'\.bets',setup)
  if len(bindings)!=1:return None
  var=bindings[0][0]
  divisors=re.findall(re.escape(var)+r'\.map\(('+IDENT+r')=>\1/([1-9][0-9]{0,6})\)',setup)
  if len(divisors)!=1:return None
  factor=int(divisors[0][1])
  if factor<=1:return None
  prices=re.findall(r'this\.buyBonusPageConfig\.params\.sections\[1\]\.options\['+str(index)+r'\]\.value=('+IDENT+r')\*'+str(factor)+r'(?=[;,])',setup)
  if len(prices)!=1:return None
  factors[command]=factor
 # The spin request forwards exactly the menu-selected command.
 arrays=re.findall(r'\[("'+COMMAND+r'","'+COMMAND+r'")\]\.some\(('+IDENT+r')=>this\.nextCommands\.includes\(\2\)\)&&\(('+IDENT+r')\.cmd=this\.nextCommands\[0\]\)',source)
 if len(arrays)!=1 or set(re.findall(r'"([^"]+)"',arrays[0][0]))!=set(commands):return None
 try:
  prices={}
  for name,record in modes.items():
   if not re.fullmatch(COMMAND,name) or not isinstance(record,dict) or isinstance(record.get('coinsPerBet'),bool):return None
   price=Decimal(str(record.get('coinsPerBet')))
   if not price.is_finite() or price<=0 or price!=price.to_integral_value():return None
   prices[name]=str(price)
 except (ValueError,TypeError,InvalidOperation):return None
 accept=re.findall(r'T\(this,"onCollect",async ('+IDENT+r')=>\{.{0,600}?('+IDENT+r')\.slotMachine\.isFreeSpin=!0,\1==="default"\)\2\.gamePlay\.play\("('+COMMAND+r')"\);else',source)
 risk=re.findall(r'T\(this,"onGamble",async\(\)=>\{.{0,300}?('+IDENT+r')\.gameState\.nextCommands\.includes\("('+COMMAND+r')"\).{0,100}?\1\.gameState\.getPlayParams\("\2"\)',source)
 award={}
 if len(accept)==len(risk)==1 and accept[0][1]==risk[0][0] and accept[0][2]!=risk[0][1]:
  award={'accept':accept[0][2],'risk':risk[0][1]}
 return {'awarded_spin_menu':award,'profile':'sdk.confirmedPurchaseCards/serverPriceDomains/v1','roles':{name:'SPIN' if name=='BASIC' else 'BUY_BONUS' for name in modes},'purchase_price_factors':factors,'current_coins_per_bet':prices,'source_sha256':hashlib.sha256(source.encode()).hexdigest()}
