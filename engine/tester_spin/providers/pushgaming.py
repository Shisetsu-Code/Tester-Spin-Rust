"""Observed Push Hive REST demo executor. Paid-control completeness stays unknown.

Protocol provenance: three requests around the captured official base spin;
one title family validated so far. No purchased feature or choice is guessed.
"""
import base64,hashlib,json,re,time
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from curl_cffi import requests
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.models import GameTestResult,SpinAttempt
from tester_spin.paid_options import write_paid_option_inventory


def parse_launcher(html):
    match=re.search(r'var gameUrl\s*=([\s\S]*?);',html)
    if not match:raise ValueError('OFFICIAL_LAUNCHER_BINDING_MISSING')
    value=''.join(re.findall(r"'([^']*)'",match[1]))
    url=urlsplit(base64.b64decode(value,validate=True).decode())
    if url.scheme!='https' or url.hostname!='player.eu.demo.pushgaming.com' or url.port not in (None,443) or url.username or url.password or url.path!='/mesh/b2c/igp/pg-com/launch':
        raise ValueError('OFFICIAL_DEMO_AUTHORITY_MISMATCH')
    query=parse_qs(url.query,keep_blank_values=True)
    if any(len(v)!=1 for v in query.values()):raise ValueError('AMBIGUOUS_LAUNCHER')
    q={k:v[0] for k,v in query.items()}
    if q.get('mode')!='DEMO' or q.get('ccyCode')!='fun' or not re.fullmatch(r'[a-z0-9-]+',q.get('rgsGameId','')) or not q.get('token'):
        raise ValueError('FICTITIOUS_DEMO_NOT_CONFIRMED')
    return q


def integer(value):
    if type(value)!=int or value<0:raise ValueError('INVALID_MINOR_AMOUNT')
    return value


def action_identity(action):
    value=action.get('actionId')
    if type(value)==int and value>=0:return str(value)
    if isinstance(value,str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',value):return value
    raise ValueError('ACTION_ID_UNBOUND')


def verify_round(paid,settled,*,before,bet):
    integer(before);integer(bet)
    if bet<=0:raise ValueError('INVALID_BET')
    for key in ('actionId','playId','hivePlayId'):
        if not paid.get(key) or paid[key]!=settled.get(key):raise ValueError('ROUND_IDENTITY_MISMATCH')
    if paid.get('actionName')!='spin' or settled.get('actionName')!='spin' or paid.get('totalBet')!=bet or settled.get('totalBet')!=bet:
        raise ValueError('ACTION_BINDING_MISMATCH')
    if settled.get('actionComplete') is not True or settled.get('endOfPlay') is not True or settled.get('availableActions')!=['spin']:
        raise ValueError('ROUND_NOT_TERMINAL')
    win=integer(settled.get('cumulativeWin'))
    data=settled.get('data')
    if data is not None:
        if not isinstance(data,list) or len(data)!=1 or data[0].get('type')!='game-response' or data[0].get('endOfRound') is not True or data[0].get('gameMode')!='base-game' or data[0].get('nextActions')!=['spin']:
            raise ValueError('CHOICE_OR_BONUS_UNBOUND')
        if integer(data[0].get('win'))!=win or integer(data[0].get('creditAmount'))!=win:
            raise ValueError('WIN_CONTRACT_UNBOUND')
    else:
        steps=settled.get('steps');state=settled.get('state')
        if not isinstance(steps,list) or not steps or not isinstance(state,dict):
            raise ValueError('CHOICE_OR_BONUS_UNBOUND')
        running=0
        for index,step in enumerate(steps):
            if step.get('stepNumber')!=index or step.get('gameMode')!='base-game' or step.get('freeSpinsWin',0)!=0:
                raise ValueError('CHOICE_OR_BONUS_UNBOUND')
            running+=integer(step.get('win'))
            if integer(step.get('cumulativeWin'))!=running:raise ValueError('STEP_WIN_CONTRACT_UNBOUND')
        if running!=win or integer(state.get('totalWin'))!=win:
            raise ValueError('STEP_WIN_CONTRACT_UNBOUND')
    if integer(paid['walletData']['walletBalance'])!=before-bet or integer(settled['walletData']['walletBalance'])!=before-bet+win:
        raise ValueError('ROUND_LEDGER_MISMATCH')
    return True


def safe(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if any(s in k.lower() for s in ('token','session','player')) else 'id-'+hashlib.sha256(str(v).encode()).hexdigest()[:16] if k in ('actionId','playId','hivePlayId','prevActionId') and v else safe(v)) for k,v in value.items()}
    if isinstance(value,list):return [safe(v) for v in value]
    return value


class PushGamingProvider(CatalogProvider):
    key='pushgaming';display_name='Push Gaming';catalog_url='https://www.pushgaming.com/games/'
    execution_supported=True
    max_test_concurrency=1

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        folder=self.game_dir(game)/'tests'/str(time.time_ns());folder.mkdir(parents=True)
        result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,0,'PARCIAL',symbol=game.symbol,run_dir=str(folder))
        errors=[];client=requests.Session(impersonate='chrome')
        def save(name,obj):(folder/name).write_text(json.dumps(safe(obj),ensure_ascii=False,indent=2),encoding='utf8')
        def call(method,url,**kwargs):
            response=client.request(method,url,timeout=timeout_s,allow_redirects=False,**kwargs)
            if response.status_code not in (200,201):raise ValueError('HTTP '+str(response.status_code)+' '+method+' '+urlsplit(url).path)
            return response
        try:
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            self.game_dir(game)  # validates catalogue authority before networking
            product=call('GET',game.url).text
            launches=set(re.findall(r'data-url=["\'](/games/play/[^"\']+\.html)["\']',product))
            if len(launches)!=1:raise ValueError('OFFICIAL_LAUNCHER_UNBOUND')
            launcher=call('GET','https://www.pushgaming.com'+next(iter(launches))).text
            q=parse_launcher(launcher);code=q['rgsGameId'];host='https://player.eu.demo.pushgaming.com'
            base=host+'/hive/b2c/game/'+code+'/api/'
            headers={'Origin':'https://player.eu.demo.pushgaming.com','Referer':host+'/',
                     'X-PG-IGPCODE':'pg-com','X-PG-JURISDICTION':q['jurisdiction'],'X-PG-CLIENT-VERSION':'1.2.8'}
            player_headers={'Origin':host,'Referer':host+'/','Content-Type':'application/json','x-pg-client-type':'HTML'}
            auth={'authToken':q['token'],'guest':True,'igpCode':'pg-com','integrationCode':'generic','mode':'DEMO',
                  'jurisdiction':q['jurisdiction'],'gameCode':code,'guestCurrencyCode':'fun','lang':q['lang'],
                  'referrer':'https://www.pushgaming.com/','lobbyUrl':q['lobbyUrl']}
            player=call('POST',host+'/rgs/b2c/player/authenticate/v1',json=auth,headers=player_headers).json()
            player_headers['Authorization']='Bearer '+player['sessionToken']
            config=call('POST',host+'/rgs/b2c/player/config/v1',headers=player_headers).json()
            login={'type':'sessionTokenLogin','igpCode':'pg-com','gameCode':code,'sessionToken':player['sessionToken'],
                   'authToken':q['token'],'currency':'fun','lang':q['lang'],'mode':'demo','jurisdiction':q['jurisdiction']}
            session=call('POST',base+'sessions',json=login,headers=headers).json()
            headers['Authorization']='Bearer '+session['sessionId']
            settings=call('GET',base+'settings',headers=headers).json()
            save('settings.json',settings);save('player-config.json',config)
            bets=settings.get('allowedBets');stakes=settings.get('allowedStakes')
            if (not isinstance(bets,list) or not bets or any(type(x)!=int or x<=0 for x in bets)
                    or not isinstance(stakes,list) or {s.get('amount') for s in stakes}!=set(bets)
                    or settings.get('currencyCode')!='fun'):
                raise ValueError('BET_DOMAIN_UNBOUND')
            balance=integer(session['wallet']['balance']);bet=min(bets)
            for index in range(spins):
                if stop_event.is_set():break
                attempt=SpinAttempt(index+1,False,mode_id='SPIN',mode_kind='SPIN',symbol=code,endpoint=base+'actions-v2')
                result.attempts.append(attempt)
                save('dispatch-'+str(index+1)+'.json',{'state':'DISPATCHED_UNCERTAIN_UNTIL_SETTLED','action':'spin','bet':bet})
                paid=call('POST',base+'actions-v2',headers=headers,json={'action':'spin','bet':bet}).json()['actions']
                if len(paid)!=1:raise ValueError('MULTIPLE_ACTIONS_UNBOUND')
                paid=paid[0];save('purchase-'+str(index+1)+'.json',paid)
                identity=action_identity(paid)
                settled=call('PUT',base+'actions-v2/'+identity,headers=headers).json()['actions']
                if len(settled)!=1:raise ValueError('MULTIPLE_SETTLEMENTS_UNBOUND')
                settled=settled[0];save('settlement-'+str(index+1)+'.json',settled)
                verify_round(paid,settled,before=balance,bet=bet)
                attempt.ok=True;attempt.terminal=True;attempt.status_code=200;attempt.wire_steps=2
                balance=settled['walletData']['walletBalance'];result.successful_spins+=1
                progress('Push Hive REST: base spin settled; complete paid inventory remains unresolved.')
            result.structural_map['push_hive']={'game_code':code,'base_quotes':bets,'base_rounds_closed':result.successful_spins,
                'availableFeatureBets':settings.get('availableFeatureBets'),'antebet_complete':False,'scope':'observed base-game REST family only'}
        except Exception as exc:
            errors.append(type(exc).__name__+': '+str(exc) if isinstance(exc,ValueError) else type(exc).__name__+': transport/bootstrap failure; inspect local phase artifacts')
        finally:client.close()
        result.failed_spins=max(0,spins-result.successful_spins)
        write_paid_option_inventory(result,primitive={'id':'pushgaming.hive.observed-base','version':1},
            source='Fresh official demo settings; client paid-control binding incomplete',options=[],complete=False,
            evidence_files=[n for n in ('settings.json','player-config.json') if (folder/n).exists()],
            unresolved=['COMPLETE_PAID_CONTROLS_AND_ANTEBET_BINDING_REQUIRED'])
        result.error='; '.join(errors+['Complete paid-option inventory remains unverified.'])
        save('result.json',result.to_dict())
        return result
