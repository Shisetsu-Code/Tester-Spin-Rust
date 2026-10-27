"""Confirmed single-card SDK purchase binding, priced by current server domains."""
import re
import hashlib
from decimal import Decimal,InvalidOperation
IDENT=r'[A-Za-z_$][\w$]*'
CMD=r'[A-Z][A-Z0-9_]{0,63}'
NUM=r'[1-9][0-9]{0,6}'
GETTER=re.compile(r'getSpinParams\(\)\{const (?P<flag>'+IDENT+r')=\["(?P<cmd>'+CMD+r')"\]\.some\((?P<item>'+IDENT+r')=>this\.nextCommands\.includes\((?P=item)\)\)\,(?P<obj>'+IDENT+r')=\{amount:(?P=flag)\?this\.bet\.get\(\)\*(?P<factor>'+NUM+r'):this\.bet\.get\(\),coin:(?P=flag)\?this\.bet\.get\(\)/(?P<coins>'+NUM+r')\*(?P=factor):this\.bet\.get\(\)/(?P=coins)\};(?P=flag)&&\((?P=obj)\.cmd=this\.nextCommands\[0\]\)')

def source_roles(source,modes):
 if not isinstance(source,str) or not isinstance(modes,dict):return None
 getters=list(GETTER.finditer(source))
 if len(getters)!=1:return None
 getter=getters[0];command=getter['cmd'];factor=int(getter['factor']);quantity=int(getter['coins'])
 if factor<=1 or set(modes)!={'BASIC',command}:return None
 section='id:"buy-bonus-cards-section",eventName:"onBuyBonusCard",options:['
 if source.count(section)!=1:return None
 cards=source.split(section,1)[1].split(']}]',1)[0]
 if len(re.findall(r'\{id:"[^"]+",active:!0,info:',cards))!=1:return None
 dispatch=re.findall(r'const ('+IDENT+r')=this\.buyBonusPageConfig,\{type:('+IDENT+r')\}=('+IDENT+r')\.detail,('+IDENT+r')=\1\.params\.sections\[1\]\.options\[0\]\.value;if\(\2==="BUY"\)this\.('+IDENT+r')\(\4\);else',source)
 if len(dispatch)!=1:return None
 handler=dispatch[0][4]
 pattern=re.compile(IDENT+r'\(this,"'+re.escape(handler)+r'",(?P<param>'+IDENT+r')=>\{const (?P<callback>'+IDENT+r')=async\(\)=>\{(?P<owner>'+IDENT+r')\.gameState\.nextCommands=\["'+re.escape(command)+r'"\];')
 matches=list(pattern.finditer(source))
 if len(matches)!=1:return None
 m=matches[0];owner=m['owner'];body=source[m.end():m.end()+2000]
 if owner+'.gameState.bet.set('+m['param']+'/'+str(factor)+')' not in body or 'this.bonusBought(!0)' not in body or 'await '+owner+'.gamePlay.start()' not in body or not re.search(r'primaryButtonAction:'+re.escape(m['callback'])+r'(?=[,}])',body):return None
 defaults=re.findall(r'const ('+IDENT+r')='+re.escape(owner)+r'\.gameState\.modes\.'+re.escape(command)+r'\.defaultBet/'+str(factor)+r';this\.betConfig\.params\.sections\[0\]\.options='+IDENT+r',this\.buyBonusPageConfig\.params\.sections\[0\]\.selectedValue=\1',source)
 if len(defaults)!=1:return None
 default=defaults[0]
 if source.count('this.buyBonusPageConfig.params.sections[1].options[0].value='+default+'*'+str(factor))!=1:return None
 bindings=re.findall(r'('+IDENT+r')='+re.escape(owner)+r'\.gameState\.modes\.'+re.escape(command)+r'\.bets',source)
 if len(bindings)!=1:return None
 loop=re.compile(re.escape(bindings[0])+r'\.forEach\(async ('+IDENT+r')=>\{\1&&'+IDENT+r'\.push\(\{title:'+IDENT+r'\(String\(\1/'+str(factor)+r'\)\),value:\1/'+str(factor)+r'\}\)\}\)')
 if len(loop.findall(source))!=1:return None
 try:
  prices={}
  for name,record in modes.items():
   if not isinstance(record,dict) or isinstance(record.get('coinsPerBet'),bool):return None
   price=Decimal(str(record.get('coinsPerBet')))
   if not price.is_finite() or price!=quantity:return None
   prices[name]=str(price)
 except (InvalidOperation,ValueError,TypeError):return None
 accepts=re.findall(r'if\(this\.mode==="default"\)('+re.escape(owner)+r')\.gamePlay\.play\("('+CMD+r')"\);else\{if\(!\1\.gamePlay\.response\)return;\1\.gamePlay\.handleCommandResult\(\1\.gamePlay\.response\)\}',source)
 award_command=accepts[0][1] if len(accepts)==1 else None
 return {'award_command':award_command,'profile':'sdk.confirmedSinglePurchaseCard/serverPriceDomains/v1','roles':{name:'SPIN' if name=='BASIC' else 'BUY_BONUS' for name in modes},'purchase_price_factors':{command:factor},'current_coins_per_bet':prices,'source_sha256':hashlib.sha256(source.encode()).hexdigest()}
