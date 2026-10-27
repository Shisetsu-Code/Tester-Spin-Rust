"""Official FUN demo, observed complex-slot init/bet/collect WebSocket family."""
import hashlib,json,re,time
from urllib.parse import urlsplit,urlencode
from curl_cffi import requests
import websocket
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.models import GameTestResult,SpinAttempt
from tester_spin.paid_options import write_paid_option_inventory

def integer(value):
    if type(value) is not int or value<0:raise ValueError('INTEGER_AMOUNT_UNBOUND')
    return value

def paid_options(initial):
    settings=initial.get('settings',{}).get('gameSettings',{}).get('complex',{})
    ids=settings.get('featureIds',{});prices=settings.get('featureMultipliers',{});result=[]
    for name,identity in ids.items():
        if name=='NONE':continue
        result.append({'id':name,'category':'bonus_purchase' if name.startswith('BUY_') else 'ante_bet' if name=='DOUBLE_CHANCE' else 'unknown',
            'execution_ids':[name],'binding':{'featureId':identity},'declared_multiplier':prices.get(str(identity))})
    return result

def base_bet(initial):
    state=initial.get('states',{}).get('gameState',{}).get('complex',{}).get('currentState',{})
    config=initial.get('settings',{}).get('gameSettings',{}).get('complex',{})
    bets=config.get('bets',[]);ids=config.get('featureIds');prices=config.get('featureMultipliers')
    if (state.get('state')!='idle' or state.get('denomination')!=1 or state.get('freespins')!=0
            or state.get('winAmount')!=0 or not bets or any(type(n) is not int or n<=0 for n in bets)):
        raise ValueError('COMPLEX_BASE_DOMAIN_UNBOUND')
    explicit=isinstance(ids,dict) and ids.get('NONE')==0 and isinstance(prices,dict) and prices.get('0')==1
    # Explicit first-party MainModel defaults + getBetData serializer, observed
    # in public slot-library.js. This binds a base request, never a zero-paid
    # declaration. Unknown engines do not inherit it.
    sdk_default=(ids in (None,{}) and prices in (None,{})
                 and initial.get('gameMetadata',{}).get('metadata',{}).get('engine')=='SingleBaseSlot'
                 and type(state.get('numberOfLines')) is int and state['numberOfLines']>0)
    if not (explicit or sdk_default) or state.get('featureId',0)!=0 or state.get('betMultiplier',1)!=1:
        raise ValueError('BASE_FEATURE_BINDING_UNBOUND')
    return {'bet':min(bets),'betMultiplier':1,'bonus':False,'featureId':0,'gameCommand':'bet'}

def verify_round(initial,request,paid,collected,*,gin):
    if initial.get('status')!='success' or initial.get('command')!='init_game' or initial.get('currency')!='FUN' or initial.get('gameMetadata',{}).get('gin')!=gin:
        raise ValueError('FUN_INIT_IDENTITY_REQUIRED')
    state=initial.get('states',{}).get('gameState',{}).get('complex',{}).get('currentState',{})
    config=initial.get('settings',{}).get('gameSettings',{}).get('complex',{})
    b=request.get('bet',{})
    if (request.get('command')!='bet' or request.get('gin')!=gin or request.get('gameNumber')!='-1' or state.get('state')!='idle'
            or state.get('denomination')!=1 or request.get('bonusData') is not None or b.get('bonus') is not False
            or b!=base_bet(initial)):
        raise ValueError('OBSERVED_BASE_BET_REQUIRED')
    cost=integer(b.get('bet'));before=integer(initial.get('balance'));win=integer(paid.get('winAmount'))
    if paid.get('command')!='bet' or paid.get('msg')!='success' or paid.get('gin')!=gin or not re.fullmatch(r'\d+',str(paid.get('gameNumber',''))):raise ValueError('BET_REPLY_IDENTITY_UNBOUND')
    complex_result=paid.get('complex',{})
    if complex_result.get('gameCommand')!='bet' or complex_result.get('freespins')!=0:raise ValueError('BONUS_CONTINUATION_UNBOUND')
    if paid.get('state')=='gamble':
        if integer(paid.get('balance'))!=before-cost or collected is None:raise ValueError('WIN_COLLECT_REQUIRED')
        if (collected.get('command')!='bet' or collected.get('msg')!='success' or collected.get('state')!='idle'
                or collected.get('gameNumber')!=paid['gameNumber'] or collected.get('winAmount')!=win
                or collected.get('gin')!=0 or collected.get('gameIdentificationNumber')!=-1):raise ValueError('COLLECT_NOT_TERMINAL')
        final=collected
    elif paid.get('state')=='idle' and win==0 and collected is None:final=paid
    else:raise ValueError('UNOBSERVED_TERMINAL_STATE')
    if final.get('pendingWinResult',{}).get('totalRemainingOverflowAmount')!=0 or integer(final.get('balance'))!=before-cost+win:
        raise ValueError('SETTLEMENT_LEDGER_MISMATCH')
    return True

def settlement_receipt(initial,request,paid,collected,*,gin):
    """A proven base-round close, independent of full paid-mode coverage."""
    verify_round(initial,request,paid,collected,gin=gin)
    final=collected if collected is not None else paid
    return {'schema':'tester-spin/amusnet-settlement/v1','state':'CLOSED',
            'gin':gin,'round_id':paid['gameNumber'],'currency':'FUN',
            'balance_before':initial['balance'],'cost':request['bet']['bet'],
            'win':paid['winAmount'],'balance_after':final['balance'],
            'collect_required':collected is not None,'paid_inventory_complete':False}


def redact(value):
    if isinstance(value,dict):return {k:('[REDACTED]' if any(s in k.lower() for s in ('session','token','player')) else redact(v)) for k,v in value.items() if k not in ('gameList','clientIdentifier','groups')}
    if isinstance(value,list):return [redact(v) for v in value]
    return value

def connection_parameters(text):
    marker=re.search(r'var\s+connectionParams\s*=\s*',text)
    if marker is None:raise ValueError('OFFICIAL_CONNECTION_PARAMETERS_MISSING')
    params,_=json.JSONDecoder().raw_decode(text[marker.end():])
    if not isinstance(params,dict):raise ValueError('INVALID_CONNECTION_PARAMETERS')
    return params

class AmusnetProvider(CatalogProvider):
    key='amusnet';display_name='Amusnet';catalog_url='https://demo.amusnet.com/online-casino'
    execution_supported=True;max_test_concurrency=1

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        folder=self.game_dir(game)/'tests'/str(time.time_ns());folder.mkdir(parents=True)
        result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,0,'PARCIAL',symbol=game.symbol,run_dir=str(folder))
        client=requests.Session(impersonate='chrome');ws=None;errors=[];evidence=[];initial={};counter=0;session=''
        def save(name,value):
            (folder/name).write_text(json.dumps(redact(value),indent=2),encoding='utf8')
            if name not in evidence:evidence.append(name)
        def call(method,url,**kwargs):
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            save('phase.json',{'method':method,'host':urlsplit(url).hostname,'path':urlsplit(url).path})
            r=client.request(method,url,timeout=timeout_s,allow_redirects=False,**kwargs)
            if r.status_code!=200:raise ValueError('HTTP '+str(r.status_code)+' '+urlsplit(url).path)
            if len(r.content)>4*1024*1024:raise ValueError('BOOTSTRAP_LIMIT')
            return r
        try:
            if not re.fullmatch(r'\d+',game.symbol):raise ValueError('OFFICIAL_GIN_REQUIRED')
            gin=int(game.symbol)
            call('GET','https://demo.amusnet.com/online-casino')
            token=call('POST','https://demo.amusnet.com/api/lobby',headers={'Origin':'https://demo.amusnet.com','Referer':'https://demo.amusnet.com/'}).json()
            if token.get('errorCode')!=1000 or token.get('message')!='SUCCESS' or not isinstance(token.get('gameLaunchToken'),str):raise ValueError('FRESH_DEMO_TOKEN_REQUIRED')
            page=call('GET','https://free.games.amusnet.io/gl/amusnet',params={'gameLaunchToken':token['gameLaunchToken'],'gameId':game.symbol,'gin':game.symbol,'amount':'500000','language':'en','client':'desktop','closeurl':'https://demo.amusnet.com'},
                headers={'Origin':'https://demo.amusnet.com','Referer':'https://demo.amusnet.com/'})
            params=connection_parameters(page.text)
            if (params.get('gameIdentificationNumber')!=game.symbol or not params.get('portalCode','').endswith('_FUN')
                    or params.get('remote') is not False or params.get('tcpHost')!='free-pod.games.amusnet.io'
                    or params.get('tcpPort')!='443' or params.get('tcpProtocol')!='wss'
                    or params.get('gameMetadata',{}).get('gin')!=gin or params.get('gameMetadata',{}).get('type')!='VIDEO_SLOT'):
                raise ValueError('OFFICIAL_FUN_COMPLEX_SLOT_REQUIRED')
            public=params.get('gameMetadata',{}).get('metadata',{}).get('gameLaunchUrl','')
            if urlsplit(public).hostname not in ('www.amusnet.com','amusnet.com') or urlsplit(public).path.rstrip('/').rsplit('/',1)[-1]!=game.slug:
                raise ValueError('CURRENT_GAME_SLUG_BINDING_UNBOUND')
            session=params['sessionKey'];ws=websocket.create_connection('wss://free-pod.games.amusnet.io/?'+urlencode({'sessionKey':session}),origin='https://free.games.amusnet.io',timeout=timeout_s)
            def exchange(command,fields):
                nonlocal counter,session
                if stop_event.is_set():raise ValueError('STOP_REQUESTED')
                counter+=1;identity='r-r_'+str(time.time_ns()//1000000)+'_'+str(counter)
                request={'command':command,**fields,'gin':gin,'sessionKey':session,'messageId':identity}
                ws.send(json.dumps(request,separators=(',',':')));deadline=time.monotonic()+timeout_s
                while time.monotonic()<deadline:
                    data=ws.recv()
                    if data=='ping':ws.send('pong');continue
                    if data in ('pong','PONG'):continue
                    if not isinstance(data,(str,bytes)) or len(data)>4*1024*1024:raise ValueError('GAME_REPLY_LIMIT')
                    response=json.loads(data)
                    if not isinstance(response,dict):raise ValueError('UNKNOWN_GAME_REPLY')
                    if response.get('messageId')!=identity:raise ValueError('UNMATCHED_WS_REPLY')
                    if response.get('command')!=command:raise ValueError('COMMAND_CORRELATION_UNBOUND')
                    if response.get('sessionKey'):session=response['sessionKey']
                    return request,response
                raise ValueError('RESPONSE_TIMEOUT_UNCERTAIN')
            _,initial=exchange('init_game',{'platformType':'desktop'})
            if initial.get('currency')!='FUN' or initial.get('status')!='success' or initial.get('gameMetadata',{}).get('gin')!=gin:raise ValueError('SERVER_FUN_MODE_REQUIRED')
            # Preserve admissible bootstrap evidence even when a new game
            # family is rejected before dispatch, so it can teach the adapter.
            save('bootstrap.json',initial);save('paid-options-observed.json',{'options':paid_options(initial),'inventory_complete':False})
            state=initial.get('states',{}).get('gameState',{}).get('complex',{}).get('currentState',{})
            settings=initial.get('settings',{}).get('gameSettings',{}).get('complex',{})
            base=base_bet(initial);bet=base['bet']
            if integer(initial['balance'])<bet:raise ValueError('INSUFFICIENT_FUN_BALANCE')
            attempt=SpinAttempt(1,False,mode_id='SPIN',mode_kind='SPIN',symbol=game.symbol,endpoint='wss://free-pod.games.amusnet.io/');result.attempts.append(attempt)
            fields={'bet':base,'gameNumber':'-1','bonusData':None}
            save('dispatch.json',{'state':'DISPATCHED_UNCERTAIN_UNTIL_SETTLED','fields':fields})
            request,paid=exchange('bet',fields);save('bet.json',{'request':request,'response':paid});collected=None
            if (paid.get('state')=='gamble' and paid.get('msg')=='success' and paid.get('gin')==gin
                    and paid.get('complex',{}).get('freespins')==0 and paid.get('complex',{}).get('gameCommand')=='bet'
                    and re.fullmatch(r'\d+',str(paid.get('gameNumber','')))):
                _,collected=exchange('bet',{'bet':{'gameCommand':'collect'},'gameNumber':paid['gameNumber']});save('collect.json',collected)
            # Keep dispatch.json as the historical intent. A separate receipt
            # proves closure only after all identity and ledger checks pass.
            save('settlement.json',settlement_receipt(initial,request,paid,collected,gin=gin))
            attempt.ok=True;attempt.terminal=True;attempt.status_code=101;attempt.wire_steps=2 if collected else 1;result.successful_spins=1
            result.structural_map['amusnet_complex']={'gin':gin,'currency':'FUN','base_rounds_closed':1,'paid_options_observed':paid_options(initial),'inventory_complete':False}
            progress('Amusnet: fresh official FUN demo bet/collect returned idle with reconciled balance.')
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc) if isinstance(exc,(ValueError,KeyError)) else type(exc).__name__+': bootstrap/transport failure')
        finally:
            if ws is not None:
                try:ws.close()
                except Exception:pass
            client.close()
        result.failed_spins=max(0,spins-result.successful_spins)
        write_paid_option_inventory(result,primitive={'id':'amusnet.complex.fun-base','version':2},source='Fresh FUN server settings + observed public SDK base defaults; client complete inventory unverified',options=paid_options(initial),complete=False,evidence_files=evidence,
            unresolved=['COMPLETE_CLIENT_PAID_INVENTORY','ALL_PAID_FEATURE_EXECUTIONS_AND_BRANCHES'])
        result.error='; '.join(errors+['Complete paid-option inventory remains unverified.'])
        save('result.json',result.to_dict());return result
