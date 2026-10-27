"""Relax engine1 demo REST family bound to observed per-game bootstrap evidence.

No invented launcher/version or paid mode. Unknown feature decisions stay partial.
"""
import json,re,time
from urllib.parse import urlsplit
from curl_cffi import requests
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.models import GameTestResult,SpinAttempt
from tester_spin.paid_options import write_paid_option_inventory


def validate_contract(contract,game):
    u=urlsplit(contract.get('endpoint',''));login=contract.get('login',{})
    if (contract.get('schema')!='relax.observed-rest-bootstrap/v1' or contract.get('game')!=game
            or u.scheme!='https' or u.hostname!='stag-casino-client.api.relaxg.net'
            or u.port not in (None,443) or u.path!='/engine1/game/' or u.username or u.password
            or u.query or u.fragment or login.get('g')!=game or login.get('mode')!='dev'
            or login.get('userid') is not None or login.get('clientid')!=''
            or login.get('partnerid')!='1' or login.get('immediatePayouts') is not False
            or not re.fullmatch(r'\d+\.\d+\.\d+',login.get('clientversion',''))
            or not re.fullmatch(r'[a-f0-9]{64}',contract.get('source_sha256',''))):
        raise ValueError('OBSERVED_DEMO_BOOTSTRAP_CONTRACT_UNBOUND')
    return True


def amount(value):
    if type(value)!=int or value<0:raise ValueError('INVALID_MINOR_AMOUNT')
    return value


def verify_round(play,ack,*,before,bet):
    if (play.get('ended') is not True or play.get('subgameTriggered') is not False
            or play.get('freeSpinAwardedCount')!=0 or play.get('roundType')!='demo'
            or play.get('payTokens') is not False or play.get('ba')!=bet or play.get('correspondingBa')!=bet
            or type(play.get('roundId'))!=int or play['roundId']<0):
        raise ValueError('ROUND_OR_FEATURE_UNBOUND')
    after=amount(before)-amount(bet)+amount(play.get('win'))
    if (play.get('stats',{}).get('currency')!='FUN' or ack.get('currency')!='FUN'
            or amount(play['stats']['b'])!=after or amount(ack.get('b'))!=after):
        raise ValueError('GAMEFINISHED_OR_LEDGER_MISMATCH')
    return True


def safe(value):
    if isinstance(value,dict):return {k:('[REDACTED]' if k.lower() in {'sid','userid','clientid'} or 'token' in k.lower() else safe(v)) for k,v in value.items()}
    if isinstance(value,list):return [safe(v) for v in value]
    return value


class RelaxProvider(CatalogProvider):
    key='relax';display_name='Relax Gaming';catalog_url='https://www.relax-gaming.com/products/casino'
    execution_supported=True;max_test_concurrency=1

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        root=self.game_dir(game);folder=root/'tests'/str(time.time_ns());folder.mkdir(parents=True)
        result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,0,'PARCIAL',symbol=game.symbol,run_dir=str(folder))
        client=requests.Session(impersonate='chrome');errors=[]
        def save(name,obj):(folder/name).write_text(json.dumps(safe(obj),indent=2),encoding='utf8')
        def post(operation,body):
            response=client.post(contract['endpoint']+operation,json=body,timeout=timeout_s,allow_redirects=False)
            if response.status_code!=200:raise ValueError('HTTP '+str(response.status_code)+' '+operation)
            obj=response.json()
            if not isinstance(obj,dict):raise ValueError('UNKNOWN_RESPONSE_SCHEMA')
            return obj
        try:
            source=root/'analysis/observed-rest-contract.json'
            if not source.is_file():raise ValueError('OBSERVED_DEMO_BOOTSTRAP_CONTRACT_REQUIRED')
            contract=json.loads(source.read_text(encoding='utf8'));validate_contract(contract,game.slug)
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            initial=post('funmoneylogin',contract['login']);save('init.json',initial)
            if initial.get('stats',{}).get('currency')!='FUN':raise ValueError('FICTITIOUS_CURRENCY_NOT_CONFIRMED')
            limits=initial.get('limits',{});bets=limits.get('legalBets')
            if not isinstance(bets,list) or not bets or any(type(b)!=int or b<=0 for b in bets):raise ValueError('LEGAL_BET_DOMAIN_UNBOUND')
            before=amount(initial['stats']['b']);bet=min(bets);sid=initial.get('sid')
            if not isinstance(sid,str) or not sid:raise ValueError('DEMO_SESSION_MISSING')
            if initial.get('refresh',{}).get('ended') is not True:raise ValueError('PREVIOUS_ROUND_UNSETTLED')
            attempt=SpinAttempt(1,False,mode_id='SPIN',mode_kind='SPIN',symbol=game.slug,endpoint=contract['endpoint']+'play')
            result.attempts.append(attempt)
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            save('dispatch.json',{'state':'DISPATCHED_UNCERTAIN_UNTIL_GAMEFINISHED','bet':bet})
            body={'g':game.slug,'sid':sid,'restoreState':{'restoreSpin':True},'restoreVersion':1,'ba':bet,'ga':'spin','timestamp':int(time.time()*1000)}
            play=post('play',body);save('play.json',play)
            if play.get('ended') is not True:raise ValueError('FEATURE_OR_DECISION_CONTINUATION_UNBOUND')
            ack=post('gamefinished',{'g':game.slug,'sid':sid,'restoreVersion':2});save('gamefinished.json',ack)
            verify_round(play,ack,before=before,bet=bet)
            attempt.ok=True;attempt.terminal=True;attempt.wire_steps=2;attempt.status_code=200;result.successful_spins=1
            result.structural_map['relax_engine1']={'source_sha256':contract['source_sha256'],'base_quotes':bets,'settlement':'ended+gamefinished+FUN_ledger','complete_paid_inventory':False}
            progress('Relax REST: official demo base spin and gamefinished reconciled; paid controls remain unverified.')
        except Exception as exc:
            errors.append(type(exc).__name__+': '+str(exc) if isinstance(exc,ValueError) else type(exc).__name__+': bootstrap/transport failure; inspect local artifacts')
        finally:client.close()
        result.failed_spins=max(0,spins-result.successful_spins)
        write_paid_option_inventory(result,primitive={'id':'relax.engine1.observed-base','version':1},source='Fresh funmoneylogin plus observed client requests; full paid controls unverified',options=[],complete=False,
            evidence_files=['init.json'] if (folder/'init.json').exists() else [],unresolved=['COMPLETE_PAID_OPTION_INVENTORY_AND_BRANCH_BINDINGS_REQUIRED'])
        result.error='; '.join(errors+['Complete paid-option inventory remains unverified.'])
        save('result.json',result.to_dict());return result
