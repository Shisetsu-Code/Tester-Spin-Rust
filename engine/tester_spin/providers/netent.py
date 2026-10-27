"""NetEnt's observed Dragon servlet family, fresh official VC0 demo sessions.

Base rounds only. Unknown bonus continuations and paid controls stay partial.
"""
import hashlib,json,re,time
from urllib.parse import urljoin,urlsplit,parse_qs
from curl_cffi import requests
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.models import GameTestResult,SpinAttempt
from tester_spin.paid_options import write_paid_option_inventory

def decode_form(text):
    if len(text)>8*1024*1024:raise ValueError('SERVLET_RESPONSE_LIMIT')
    values=parse_qs(text,keep_blank_values=True)
    if not values or any(len(v)!=1 for v in values.values()):raise ValueError('AMBIGUOUS_SERVLET_FIELDS')
    return {k:v[0] for k,v in values.items()}

def integer(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+',value):raise ValueError('INVALID_INTEGER_DOMAIN')
    return int(value)

def base_cost(initial,request):
    if request.get('action')!='spin' or request.get('ne_mode')!='demo' or request.get('ne_currency')!='VC0':
        raise ValueError('OFFICIAL_FUN_MODE_REQUIRED')
    level=integer(request.get('bet.betlevel'));denom=integer(request.get('bet.denomination'))
    if level<=0 or denom<=0 or str(level) not in initial.get('betlevel.all','').split(',') or str(denom) not in initial.get('denomination.all','').split(','):
        raise ValueError('BET_DOMAIN_UNBOUND')
    ids=sorted(integer(v) for k,v in initial.items() if re.fullmatch(r'bl\.i\d+\.id',k))
    if not ids or len(ids)>1000 or ids!=list(range(len(ids))) or request.get('bet.betlines')!=f'0-{len(ids)-1}':
        raise ValueError('LINE_DOMAIN_UNBOUND')
    coins=[integer(initial.get(f'bl.i{i}.coins')) for i in ids]
    if any(c<=0 for c in coins):raise ValueError('LINE_COST_UNBOUND')
    return sum(coins)*level*denom

def verify_base_round(initial,request,response):
    total=base_cost(initial,request)
    for row in (initial,response):
        if (row.get('playforfun')!='true' or row.get('playercurrencyiso')!='VC0'
                or row.get('gameover')!='true' or row.get('gamestate.current')!='basic' or row.get('nextaction')!='spin'):
            raise ValueError('FUN_BASE_ROUND_NOT_TERMINAL')
    win=integer(response.get('game.win.cents'))
    if integer(response.get('totalwin.cents'))!=win or integer(response.get('credit'))!=integer(initial.get('credit'))-total+win:
        raise ValueError('ROUND_LEDGER_MISMATCH')
    return True

def safe_projection(values):
    return {k:v for k,v in values.items() if k in ('credit','playforfun','gameover','gamestate.current','nextaction','totalwin.cents','game.win.cents','playercurrencyiso','betlevel.all','denomination.all')
            or re.fullmatch(r'bl\.i\d+\.(?:id|coins)',k)}

def validate_entry_fragment(fragment,table_id):
    balances=fragment.get('balance_id',[])
    if (fragment.get('demo')!=['direct'] or fragment.get('provider')!=['netent'] or fragment.get('table_id')!=[table_id]
            or len(balances)!=1 or not balances[0].startswith('demo-')):
        raise ValueError('FRESH_VIRTUAL_BALANCE_UNBOUND')
    return True

class NetEntProvider(CatalogProvider):
    key='netent';display_name='NetEnt';catalog_url='https://netent.com/games'
    # Keep the prototype out of the native registry until a fresh servlet init
    # and live terminal canary pass. Captured fixtures alone are insufficient.
    execution_supported=False;max_test_concurrency=1

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        folder=self.game_dir(game)/'tests'/str(time.time_ns());folder.mkdir(parents=True)
        result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,0,'PARCIAL',symbol=game.symbol,run_dir=str(folder))
        client=requests.Session(impersonate='chrome');errors=[];evidence=[]
        def save(name,value):
            (folder/name).write_text(json.dumps(value,indent=2),encoding='utf8');evidence.append(name)
        def call(method,url,expected=(200,),**kwargs):
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            save('phase.json',{'method':method,'host':urlsplit(url).hostname,'path':urlsplit(url).path.split(';')[0]})
            reply=client.request(method,url,timeout=timeout_s,**kwargs)
            if reply.status_code not in expected:raise ValueError('HTTP '+str(reply.status_code)+' '+urlsplit(url).path.split(';')[0])
            if len(reply.content)>8*1024*1024:raise ValueError('BOOTSTRAP_RESPONSE_LIMIT')
            return reply
        try:
            if not re.fullmatch(r'[A-Za-z0-9]{1,60}',game.symbol):raise ValueError('PUBLIC_TABLE_ID_REQUIRED')
            page=call('GET','https://netent.com/demo/'+game.symbol,allow_redirects=False)
            assets=re.findall(r'<script[^>]+src="([^"]+)"',page.text)
            apps=[urljoin(page.url,a) for a in assets if re.search(r'/_app-[\w-]+\.js$',a)]
            if len(apps)!=1 or urlsplit(apps[0]).hostname!='netent.com':raise ValueError('PUBLIC_DEMO_CLIENT_UNBOUND')
            source=call('GET',apps[0],allow_redirects=False)
            keys=set(re.findall(r'set\("x-api-key","([^"]+)"\)',source.text))
            if len(keys)!=1:raise ValueError('PUBLIC_DEMO_HEADER_BINDING_UNBOUND')
            token=call('POST','https://jinx.prod.cmsevo.com/api/v1/oss/token/demo',
                json={'demo':{'language':'en-GB','currency':'VC0'},'game':{'tableId':game.symbol}},
                headers={'x-api-key':keys.pop(),'Origin':'https://netent.com','Referer':'https://netent.com/'},allow_redirects=False).json()
            entry=urljoin('https://fansite.evo-games.com',token['entry']);u=urlsplit(entry)
            if u.scheme!='https' or u.hostname!='fansite.evo-games.com' or u.path!='/entry':raise ValueError('OFFICIAL_DEMO_ENTRY_UNBOUND')
            landing=call('GET',entry);u=urlsplit(landing.url);fragment=parse_qs(u.fragment)
            if u.hostname!='fansite.evo-games.com':raise ValueError('OFFICIAL_ENTRY_HOST_CHANGED')
            validate_entry_fragment(fragment,game.symbol)
            setup=call('GET','https://fansite.evo-games.com/setup',params={'device':'desktop','wrapped':'false','locale':'en-GB'}).json()
            config=call('GET','https://fansite.evo-games.com/config',params={'table_id':game.symbol,'client_version':setup['version']}).json()
            wrapped=config.get('wrappedLaunchParams',{});server=wrapped.get('gameServer','');w=urlsplit(server)
            if (config.get('table_id')!=game.symbol or config.get('game_provider')!='netent'
                    or w.scheme!='https' or w.hostname!='fansite.evo-games.com' or w.path!='/public/rng/dragon'
                    or wrapped.get('ne_currency')!='VC0' or not wrapped.get('sessionId') or not wrapped.get('gameId')):
                raise ValueError('OBSERVED_DRAGON_DEMO_FAMILY_REQUIRED')
            endpoint=server+'/servlet/CasinoGameServlet;jsession='+wrapped['sessionId']
            shared={'sessid':wrapped['sessionId'],'gameId':wrapped['gameId'],'wantsfreerounds':'true','freeroundmode':'false','wantsreels':'true',
                    'ne_currency':'VC0','ne_mode':'demo','ne_balance_id':fragment['balance_id'][0]}
            for key in ('ne_evo_token','ne_evo_token1','ne_evo_token2','ne_device','ne_casinoId'):
                if not isinstance(wrapped.get(key),str) or not wrapped[key]:raise ValueError('FRESH_SESSION_BINDING_MISSING')
                shared[key]=wrapped[key]
            # The first-party launcher initializes the servlet's game context.
            # Resolve its game resource from the current official directory.
            static=wrapped.get('staticServer','');static_url=urlsplit(static)
            if static_url.scheme!='https' or static_url.hostname!='fansite000000001-static2.casinomodule.com':
                raise ValueError('OFFICIAL_STATIC_AUTHORITY_UNBOUND')
            directory=call('GET',urljoin(static,'gameinclusion/directory/directory.json')).json()
            alias=wrapped['gameId'].removesuffix('_sw')
            resource=directory.get(alias)
            if not isinstance(resource,str) or not re.fullmatch(r'games/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.json',resource):
                raise ValueError('CURRENT_GAME_RESOURCE_UNBOUND')
            metadata=call('GET',urljoin(static,resource)).json();relative=metadata.get('relativeLoaderUrl','')
            if not re.fullmatch(r'game/[A-Za-z0-9_-]+\.xhtml',relative):raise ValueError('OBSERVED_XHTML_LOADER_REQUIRED')
            location=resource.rsplit('/',1)[0]+'/'
            form={**shared,'oss':'true','languageDirection':'left-to-right','launchType':'iframe','disableDeviceDetection':'true',
                  'depositAvailable':'false','disableLogging':'true','environment':'LIVE','enableSentry':'false',
                  'jurisdictionCode':setup.get('geo',{}).get('country',''),'gameRulesJurisdiction':'XT',
                  'bettingModes.0':'cash','bettingModes.1':'coins','agBalanceEnabled':'true','showHomeButton':'false',
                  'gameLocation':location,'preBuiltGameRulesSupported':'false','server':server+'/',
                  'lang':wrapped.get('language','en'),'operatorId':wrapped['ne_casinoId'],
                  'gameURL':urljoin(static,location+relative)}
            for k in ('wantsfreerounds','freeroundmode','wantsreels'):form.pop(k,None)
            launch=call('POST',server+'/mobile-game-launcher/GameLauncher',data=form,allow_redirects=False,expected=(302,))
            if urlsplit(launch.headers.get('Location','')).hostname!=static_url.hostname:raise ValueError('GAME_LAUNCH_REDIRECT_UNBOUND')
            servlet_headers={'Origin':static.rstrip('/'),'Referer':launch.headers['Location']}
            initial=decode_form(call('GET',endpoint,headers=servlet_headers,params={**shared,'action':'init','no-cache':str(time.time_ns()//1000000)}).text)
            save('bootstrap-summary.json',{'public_client_sha256':hashlib.sha256(source.content).hexdigest(),'table_id':game.symbol,
                'runtime_game_id':wrapped['gameId'],'initial':safe_projection(initial),'initial_field_names':list(initial),
                'initial_error_codes':{k:v for k,v in initial.items() if k in ('errorcode','evo-error-code') and re.fullmatch(r'[A-Za-z0-9_.:-]{1,60}',v)},'inventory_complete':False})
            if not initial.get('betlevel.all') or not initial.get('denomination.all'):raise ValueError('SERVLET_INITIAL_BET_DOMAIN_UNBOUND')
            ids=[k for k in initial if re.fullmatch(r'bl\.i\d+\.id',k)]
            request={'action':'spin','ne_mode':'demo','ne_currency':'VC0','bet.betlevel':str(min(integer(x) for x in initial['betlevel.all'].split(','))),
                     'bet.denomination':str(min(integer(x) for x in initial['denomination.all'].split(','))),'bet.betlines':f'0-{len(ids)-1}'}
            cost=base_cost(initial,request)
            # Validate idle virtual state before any wager is dispatched.
            if any(initial.get(k)!=v for k,v in {'playforfun':'true','playercurrencyiso':'VC0','gameover':'true','gamestate.current':'basic','nextaction':'spin'}.items()):
                raise ValueError('INITIAL_FUN_STATE_NOT_IDLE')
            if integer(initial.get('credit'))<cost:raise ValueError('INSUFFICIENT_VIRTUAL_BALANCE')
            attempt=SpinAttempt(1,False,mode_id='SPIN',mode_kind='SPIN',symbol=wrapped['gameId'],endpoint=server+'/servlet/CasinoGameServlet');result.attempts.append(attempt)
            save('dispatch.json',{'state':'DISPATCHED_UNCERTAIN_UNTIL_VERIFIED','request':request,'cost_minor':cost})
            reply=decode_form(call('GET',endpoint,headers=servlet_headers,params={**shared,**request,'no-cache':str(time.time_ns()//1000000)}).text)
            save('base-round.json',{'request':request,'response':safe_projection(reply)})
            verify_base_round(initial,request,reply)
            attempt.ok=True;attempt.terminal=True;attempt.status_code=200;attempt.wire_steps=1;result.successful_spins=1
            result.structural_map['netent_dragon']={'fun_currency':'VC0','base_cost_minor':cost,'closed_base_rounds':1,'inventory_complete':False}
            progress('NetEnt Dragon: fresh official VC0 demo base spin closed with reconciled credit.')
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc) if isinstance(exc,(ValueError,KeyError)) else type(exc).__name__+': bootstrap/transport failure')
        finally:client.close()
        result.failed_spins=max(0,spins-result.successful_spins)
        write_paid_option_inventory(result,primitive={'id':'netent.dragon.observed-fun-base','version':1},source='Fresh official VC0 demo; complete paid control inventory unknown',options=[],complete=False,
            evidence_files=evidence,unresolved=['COMPLETE_PAID_OPTION_INVENTORY','BONUS_CONTINUATION_BINDINGS'])
        result.error='; '.join(errors+['Complete paid-option inventory remains unverified.'])
        save('result.json',result.to_dict());return result
