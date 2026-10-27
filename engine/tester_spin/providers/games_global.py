"""Observed Games Global AdvancedSlotsFilter public practice-play family."""
import copy,hashlib,json,re,time,uuid
from decimal import Decimal,InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit,parse_qs
from xml.etree import ElementTree as ET
from curl_cffi import requests
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.models import GameTestResult,SpinAttempt
from tester_spin.paid_options import write_paid_option_inventory

def integer(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+',value):raise ValueError('INTEGER_DOMAIN_UNBOUND')
    return int(value)

def minor(value):
    try:n=Decimal(str(value))*100
    except InvalidOperation:raise ValueError('FINANCIAL_AMOUNT_UNBOUND')
    if not n.is_finite() or n<0 or n!=n.to_integral_value():raise ValueError('FINANCIAL_PRECISION_UNBOUND')
    return int(n)

def packet(envelope,*,mid,cid,sid):
    p=envelope.get('packet',{})
    text=p.get('payload','')
    if p.get('packetType')!=8 or p.get('isBase64Encoded') is not False or not isinstance(text,str) or len(text)>8*1024*1024 or '<!DOCTYPE' in text.upper():
        raise ValueError('OBSERVED_XML_PACKET_REQUIRED')
    root=ET.fromstring(text);identity=root.find('Id')
    if root.tag!='Pkt' or root.get('version') not in (None,'6.1') or identity is None or identity.get('verb') not in ('Refresh','Spin','FreeSpin') or any(identity.get(k)!=v for k,v in {'mid':mid,'cid':cid,'sid':sid}.items()):
        raise ValueError('GAME_PACKET_IDENTITY_MISMATCH')
    user=root.find('Response/User')
    if user is None or user.get('type')!='DemoUser':raise ValueError('SERVER_DEMO_USER_REQUIRED')
    integer(user.get('bal'))
    return root

def ready_base(root):
    core=root.find('Response/Core')
    if core is None:raise ValueError('STAGE_GRAPH_UNKNOWN')
    available=[s for s in core.findall('Stage') if s.get('avail')=='True']
    if (len(available)!=1 or available[0].get('name')!='BaseGame' or available[0].get('remain')!='1'
            or available[0].get('index')!=core.get('next')):
        raise ValueError('CHOICE_OR_BONUS_CONTINUATION_UNBOUND')
    if any(s is not available[0] and integer(s.get('remain'))!=0 for s in core.findall('Stage')):
        raise ValueError('UNFINISHED_STAGE')
    return available[0]

def declared_actions(root):
    base=ready_base(root);result={}
    domain=base.find('PossibleBets')
    if domain is None or not list(domain):raise ValueError('POSSIBLE_BETS_UNKNOWN')
    for item in domain:
        name=item.get('value');bet=item.find('Bet')
        if item.tag!='Action' or not name or name in result or bet is None:raise ValueError('AMBIGUOUS_ACTION_DOMAIN')
        result[name]=dict(bet.attrib)
    return result

def base_request(root):
    actions=declared_actions(root);normal=actions.get('Play',{})
    if normal.get('name')!='NormalBet' or set(normal)!={'name','principal'}:raise ValueError('NORMAL_BET_CONTRACT_UNBOUND')
    settings=root.find('Response/Settings')
    if settings is None:raise ValueError('BET_SETTINGS_UNKNOWN')
    level=integer(settings.get('minlevel'));denom=min(integer(n) for n in settings.get('denoms','').split(','));principal=integer(normal.get('principal'))
    if min(level,denom,principal)<=0:raise ValueError('POSITIVE_QUOTE_REQUIRED')
    return {'verbex':'Spin','action':'Play','name':'BaseGame','denom':str(denom),'level':str(level),'wager':str(principal*level*denom)}

def paid_options(actions):
    options=[]
    for action,bet in actions.items():
        if action=='Play' and bet.get('name')=='NormalBet':continue
        category={'DoubleBet':'ante_bet','GuaranteeBet':'ante_bet','BonusBet':'bonus_purchase'}.get(bet.get('name'),'unknown')
        options.append({'id':action,'category':category,'execution_ids':[action],
                        'binding':{'verbex':'Spin','action':action,'stage':'BaseGame'},'declared_price_terms':bet})
    return options

def verify_base_round(initial,request,response,*,mid,cid,sid):
    before=packet(initial,mid=mid,cid=cid,sid=sid);after=packet(response,mid=mid,cid=cid,sid=sid)
    ready_base(before);ready_base(after)
    req=ET.fromstring(request['packet']['payload']);identity=req.find('Id');action=req.find('Request')
    if identity is None or any(identity.get(k)!=v for k,v in {'mid':mid,'cid':cid,'sid':sid,'verb':'AdvSlot'}.items()) or action is None or action.get('verbex')!='Spin' or action.get('name')!='BaseGame':
        raise ValueError('SPIN_REQUEST_UNBOUND')
    domain=declared_actions(before)
    if action.get('action') not in domain:raise ValueError('ACTION_NOT_DECLARED')
    cost=integer(action.get('wager'))+integer(action.get('sideBet','0'))
    context=response.get('context',{});financials=context.get('financials',{});balances=context.get('balances',{})
    if context.get('isReadOnly') is not False or minor(financials.get('betAmount'))!=cost:raise ValueError('CHARGED_COST_MISMATCH')
    payout=minor(financials.get('payoutAmount'));balance=integer(after.find('Response/User').get('bal'))
    before_balance=integer(before.find('Response/User').get('bal'))
    if (minor(initial.get('context',{}).get('balances',{}).get('totalInAccountCurrency'))!=before_balance
            or minor(balances.get('totalInAccountCurrency'))!=balance or balance!=before_balance-cost+payout
            or minor(financials.get('totalTransactionBetAmount'))!=cost
            or minor(financials.get('totalTransactionPayoutAmount'))!=payout):
        raise ValueError('ROUND_LEDGER_MISMATCH')
    return True

class RedirectForm(HTMLParser):
    def __init__(self):super().__init__();self.active=False;self.action='';self.fields={}
    def handle_starttag(self,tag,attributes):
        a=dict(attributes)
        if tag=='form' and a.get('id')=='conform':
            if self.action:raise ValueError('AMBIGUOUS_LAUNCH_FORM')
            self.active=True;self.action=a.get('action','')
        if tag=='input' and self.active and a.get('name'):
            if a['name'] in self.fields:raise ValueError('AMBIGUOUS_LAUNCH_FIELDS')
            self.fields[a['name']]=a.get('value','')
    def handle_endtag(self,tag):
        if tag=='form':self.active=False

def safe_envelope(value):
    result=copy.deepcopy(value);root=ET.fromstring(result['packet']['payload'])
    for node in root.iter():
        for key in list(node.attrib):
            if 'session' in key.lower() or node.tag=='User' and key=='id':node.set(key,'REDACTED')
    result['packet']['payload']=ET.tostring(root,encoding='unicode');return result

class GamesGlobalProvider(CatalogProvider):
    key='games_global';display_name='Games Global';catalog_url='https://www.gamesglobal.com/Products'
    execution_supported=True;max_test_concurrency=1

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        folder=self.game_dir(game)/'tests'/str(time.time_ns());folder.mkdir(parents=True)
        result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,0,'PARCIAL',symbol=game.symbol,run_dir=str(folder))
        client=requests.Session(impersonate='chrome');errors=[];evidence=[];actions={}
        def save(name,value):
            (folder/name).write_text(json.dumps(value,indent=2),encoding='utf8')
            if name not in evidence:evidence.append(name)
        def call(method,url,**kwargs):
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            save('phase.json',{'method':method,'host':urlsplit(url).hostname,'path':urlsplit(url).path})
            reply=client.request(method,url,timeout=timeout_s,**kwargs)
            if reply.status_code!=200:raise ValueError('HTTP '+str(reply.status_code)+' '+urlsplit(url).path)
            if len(reply.content)>8*1024*1024:raise ValueError('RESPONSE_LIMIT')
            return reply
        try:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',game.symbol):raise ValueError('OFFICIAL_LAUNCH_SYMBOL_REQUIRED')
            redirector=call('GET','https://www.gamesglobal.com/api/launch/'+game.symbol,params={'launchAsMobile':'false'})
            u=urlsplit(redirector.url)
            if u.hostname!='redirector32.valueactive.eu' or parse_qs(u.query).get('playmode')!=['demo']:raise ValueError('PUBLIC_DEMO_REDIRECT_UNBOUND')
            form=RedirectForm();form.feed(redirector.text)
            target=urlsplit(form.action)
            if target.scheme!='https' or target.hostname!='gamelauncheruat.gameassists.co.uk' or target.path!='/launcher/Generic' or form.fields.get('playmode')!='demo':
                raise ValueError('OFFICIAL_DEMO_FORM_REQUIRED')
            if form.fields.get('gameName','').lower()!=game.symbol.lower()+'desktop':raise ValueError('DEMO_GAME_BINDING_MISMATCH')
            launch=call('GET',form.action,params=form.fields);u=urlsplit(launch.url);q=parse_qs(u.query)
            save('launch-review.json',{'host':u.hostname,'path':u.path,'demo_flags':{k:q.get(k) for k in ('ispracticeplay','playmode','siteid')},'query_keys':list(q)})
            if (u.scheme!='https' or u.hostname!='mobile32.gameassists.co.uk' or u.path!='/htmlgames/game/ggl'
                    or q.get('ispracticeplay')!=['true'] or q.get('playmode')!=['demo'] or q.get('siteid')!=['UAT']):raise ValueError('PRACTICE_PLAY_REQUIRED')
            ids={name:q.get(name,[''])[0] for name in ('moduleid','clientid','productid')}
            for value in ids.values():integer(value)
            if q.get('casinoid')!=[ids['productid']]:raise ValueError('DEMO_PRODUCT_BINDING_MISMATCH')
            mid,cid,sid=ids['moduleid'],ids['clientid'],ids['productid'];api='https://api32.gameassists.co.uk'
            headers={'Origin':'https://mobile32.gameassists.co.uk','Referer':'https://mobile32.gameassists.co.uk/','Content-Type':'application/json','X-ClientTypeId':'70','X-CorrelationId':str(uuid.uuid4())}
            login=call('POST',api+'/casino/user/public/v1/accounts/login/demo',params={'fields':'core,balance,session'},headers=headers,
                json={'sessionProductId':int(sid),'numLaunchTokens':10,'environment':{'clientTypeId':70,'languageCode':'en'},
                      'deviceAttributes':[{'shortCode':'bn','value':'Mozilla'},{'shortCode':'dos','value':'Windows'},{'shortCode':'ff','value':'desktop'}],
                      'context':{'moduleId':int(mid),'clientId':int(cid),'intent':1}}).json()
            core=login['account']['core']
            if core.get('userTypeId')!=5 or core.get('isExternalAccount') is not False or core.get('isExternalBalance') is not False:
                raise ValueError('ANONYMOUS_DEMO_ACCOUNT_REQUIRED')
            auth=call('POST',api+'/Shared/Communications/Public/v1/accounts/authenticate',headers={**headers,'hostApplicationId':'2','clientTypeId':'70','cwaSessionId':str(uuid.uuid4())},
                json={'launchToken':login['tokens']['launchTokens'][0],'numberOfLaunchTokens':5,'productId':int(sid)}).json()
            if auth.get('userType')!=5 or auth.get('sessionProductId')!=int(sid):raise ValueError('FRESH_DEMO_AUTH_REQUIRED')
            headers.update(Authorization='Bearer '+auth['userTokenDetails']['userToken'],**{'X-Route-ProductId':sid,'X-Route-ModuleId':mid})
            endpoint=api+f'/casino/play/public/v1/games/module/{mid}/client/{cid}/play'
            def exchange(attributes):
                root=ET.Element('Pkt',version='6.1');ET.SubElement(root,'Id',mid=mid,cid=cid,sid=sid,verb='AdvSlot');ET.SubElement(root,'Request',attributes)
                request={'packet':{'packetType':7,'payload':ET.tostring(root,encoding='unicode'),'useFilter':True,'filter':'AdvancedSlotsFilter','isBase64Encoded':False},'context':{}}
                response=call('POST',endpoint,headers=headers,json=request).json();packet(response,mid=mid,cid=cid,sid=sid)
                return request,response
            _,initial=exchange({'verbex':'Refresh'});root=packet(initial,mid=mid,cid=cid,sid=sid)
            actions=declared_actions(root);request=base_request(root)
            save('bootstrap.json',safe_envelope(initial));save('paid-actions.json',{'actions':actions,'inventory_complete':False,'source':'Current server PossibleBets; full client inventory not verified'})
            attempt=SpinAttempt(1,False,mode_id='SPIN',mode_kind='SPIN',symbol=game.symbol,endpoint=endpoint);result.attempts.append(attempt)
            save('dispatch.json',{'state':'DISPATCHED_UNCERTAIN_UNTIL_VERIFIED','request':request})
            req,reply=exchange(request);save('round.json',{'request':safe_envelope(req),'response':safe_envelope(reply)})
            verify_base_round(initial,req,reply,mid=mid,cid=cid,sid=sid)
            attempt.ok=True;attempt.terminal=True;attempt.status_code=200;attempt.wire_steps=1;result.successful_spins=1
            result.structural_map['games_global_advanced_slots']={'mid':mid,'cid':cid,'sid':sid,'declared_actions':actions,'base_rounds_closed':1,'inventory_complete':False}
            progress('Games Global: fresh official practice-play spin closed with reconciled XML and financial balances.')
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc) if isinstance(exc,(ValueError,KeyError)) else type(exc).__name__+': bootstrap/transport failure')
        finally:client.close()
        result.failed_spins=max(0,spins-result.successful_spins)
        write_paid_option_inventory(result,primitive={'id':'games-global.advanced-slots.observed-demo','version':1},source='Fresh official demo; server action domain preserved, complete client coverage unknown',options=paid_options(actions),complete=False,
            evidence_files=evidence,unresolved=['COMPLETE_CLIENT_PAID_INVENTORY','PAID_ACTION_EXECUTIONS_AND_CONTINUATIONS'])
        result.error='; '.join(errors+['Complete paid-option inventory remains unverified.'])
        save('result.json',result.to_dict());return result
