"""Observed Playson XML TEST demo executor; paid options remain unverified."""
import json,re,time
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from curl_cffi import requests
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.models import GameTestResult,SpinAttempt
from tester_spin.paid_options import write_paid_option_inventory


def validate_contract(contract,slug):
    u=urlsplit(contract.get('endpoint',''));c=contract.get('connect',{})
    if (contract.get('schema')!='playson.observed-test-bootstrap/v1' or contract.get('slug')!=slug
            or u.scheme!='https' or u.hostname!='demo.0y81pm-c-o6pywcq.com' or u.port not in (None,443)
            or u.path!='/' or u.query or u.username or u.password
            or not re.fullmatch(r'TEST\d+',c.get('playerguid','')) or c.get('wl')!='demomode'
            or c.get('gameid')!=contract.get('game_id') or c.get('command')!='connect'
            or set(contract.get('query',{}))!={'gid','wlCode','projectId'}
            or not re.fullmatch(r'[a-f0-9]{64}',contract.get('source_sha256',''))):
        raise ValueError('OBSERVED_TEST_BOOTSTRAP_UNBOUND')
    return True


def money(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+',value):raise ValueError('INVALID_MINOR_AMOUNT')
    return int(value)


def verify_purchase_debit(declaration,event):
    """Verify only an observed purchase acceptance; bonus settlement is separate.

    The server's cash-bet is the base cost even for purchased bonuses.
    Never certify the paid inventory or a terminal round from this debit.
    """
    buy=event.get('buy') or {};game=event.get('game') or {}
    if (event.get('command')!='bet' or event.get('status')!='bonus' or event.get('state')!='bonus'
            or buy.get('freegame')!='true' or game.get('bonus_game_type')!='bought'):
        raise ValueError('PURCHASE_ACCEPTANCE_UNBOUND')
    index=money(buy.get('type'))
    if game.get('bonus_game_sub_type')!=str(index):raise ValueError('PURCHASE_TYPE_MISMATCH')
    domain=declaration.get('buy_feature_cost')
    if not isinstance(domain,str):raise ValueError('PURCHASE_PRICE_DOMAIN_UNKNOWN')
    multipliers=[money(v) for v in domain.split(',')]
    if index>=len(multipliers) or any(v<=0 for v in multipliers):raise ValueError('PURCHASE_PRICE_UNBOUND')
    base=money(game.get('cash-bet'))
    if base<=0 or money(game.get('cash-bet-game'))!=base or money(game.get('cash-win'))!=0:
        raise ValueError('PURCHASE_BASE_OR_IMMEDIATE_WIN_UNBOUND')
    before=event.get('wallet_before');after=event.get('wallet_after');cost=base*multipliers[index]
    if type(before) is not int or type(after) is not int or min(before,after)<0 or before-after!=cost:
        raise ValueError('PURCHASE_DEBIT_MISMATCH')
    return {'type':index,'multiplier':multipliers[index],'base_minor':base,'cost_minor':cost,
            'accepted':True,'terminal':False,'inventory_complete':False}


def verify_round(root,*,before,total):
    state=root.find('state');game=root.find('game');cash=root.find('user_new');roundnum=root.find('roundnum')
    if (root.tag!='server' or root.get('command')!='bet' or root.get('status')!='ok'
            or state is None or state.get('current_state')!='idle' or game is None or cash is None
            or roundnum is None or not re.fullmatch(r'\d+',roundnum.get('value',''))):
        raise ValueError('ROUND_NOT_TERMINAL')
    if any(money(game.get(k))!=0 for k in ('bonus_games','original_bonus_games','prize_games','miniprize_games')):
        raise ValueError('BONUS_BRANCH_UNBOUND')
    if money(game.get('cash-bet'))!=total or money(game.get('cash-bet-game'))!=total:
        raise ValueError('BET_COST_MISMATCH')
    if money(cash.get('cash'))!=before-total+money(game.get('cash-win')):
        raise ValueError('ROUND_LEDGER_MISMATCH')
    return True


def redact(root):
    for node in root.iter():
        for key in list(node.attrib):
            if key.lower() in {'session','_uip','wlid','gs_id','prid','playerguid'}:node.set(key,'REDACTED')
    return ET.tostring(root,encoding='unicode')


class PlaysonProvider(CatalogProvider):
    key='playson';display_name='Playson';catalog_url='https://m.playson.com/games'
    execution_supported=True;max_test_concurrency=1

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        root=self.game_dir(game);folder=root/'tests'/str(time.time_ns());folder.mkdir(parents=True)
        result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,0,'PARCIAL',symbol=game.symbol,run_dir=str(folder))
        client=requests.Session(impersonate='chrome');errors=[];session='';counter=0
        def exchange(command,attributes,children=()):
            nonlocal session,counter
            counter+=1;rnd=str(time.time_ns()//1000000);attributes={**attributes,'rnd':rnd,'command':command}
            node=ET.Element('client',attributes)
            for tag,attrs in children:ET.SubElement(node,tag,attrs)
            body=ET.tostring(node,encoding='utf-8');(folder/f'{counter:03}-{command}-request.xml').write_text(redact(ET.fromstring(body)),encoding='utf8')
            response=client.post(contract['endpoint']+command,params={**contract['query'],'r':rnd},data=body,
                headers={'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','Origin':'https://playson.com','Referer':'https://playson.com/'},timeout=timeout_s,allow_redirects=False)
            if response.status_code!=200:raise ValueError('HTTP '+str(response.status_code)+' '+command)
            if len(response.content)>8*1024*1024 or b'<!DOCTYPE' in response.content.upper():raise ValueError('XML_CONTRACT_LIMIT')
            reply=ET.fromstring(response.content);(folder/f'{counter:03}-{command}-response.xml').write_text(redact(ET.fromstring(response.content)),encoding='utf8')
            if reply.tag!='server' or reply.get('command')!=command or reply.get('rnd')!=rnd:raise ValueError('RESPONSE_CORRELATION_UNBOUND')
            if reply.get('session'):session=reply.get('session')
            return reply
        try:
            source=root/'analysis/observed-rest-contract.json'
            if not source.is_file():raise ValueError('OBSERVED_TEST_BOOTSTRAP_REQUIRED')
            contract=json.loads(source.read_text(encoding='utf8'));validate_contract(contract,game.slug)
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            connected=exchange('connect',contract['connect'],[('debug',contract['debug'])])
            user=connected.find('user')
            if not session or user is None or user.get('is_test')!='true' or user.get('wl_code_id')!='demomode':raise ValueError('SERVER_TEST_MODE_NOT_CONFIRMED')
            initial=exchange('reconnect',{'session':session,'snd':'1','spn':'0'})
            state=initial.find('state');version=initial.find('source');stakes=initial.findtext('extra/stakeIncrement')
            if initial.get('status')!='ok' or state is None or state.get('current_state')!='idle':raise ValueError('SESSION_NOT_IDLE')
            if version is None or version.get('game-ver')!=contract['source_game_version']:raise ValueError('OBSERVED_PRICE_VERSION_CHANGED')
            if not stakes or contract['quote']['line_bet'] not in stakes.split(','):raise ValueError('BET_DOMAIN_UNBOUND')
            before=money(initial.find('user_new').get('cash'));total=money(contract['quote']['total_minor'])
            (folder/'bootstrap-summary.json').write_text(json.dumps({'test_mode':True,'source_sha256':contract['source_sha256'],'base_line_bets':stakes.split(','),'observed_quote':contract['quote'],'paid_domain':initial.find('game').attrib if initial.find('game') is not None else None},indent=2),encoding='utf8')
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            attempt=SpinAttempt(1,False,mode_id='SPIN',mode_kind='SPIN',symbol=contract['game_id'],endpoint=contract['endpoint']+'bet');result.attempts.append(attempt)
            reply=exchange('bet',{'session':session,'snd':'1','spn':'0','_btn':'0','_auto':'0'},[('bet',{'cash':contract['quote']['line_bet']})])
            verify_round(reply,before=before,total=total)
            attempt.ok=True;attempt.terminal=True;attempt.status_code=200;attempt.wire_steps=1;result.successful_spins=1
            result.structural_map['playson_xml']={'test_mode':True,'observed_quote':contract['quote'],'paid_domain':initial.find('game').attrib if initial.find('game') is not None else None,'inventory_complete':False}
            progress('Playson XML: TEST base bet ended idle with reconciled wallet; paid routes remain unverified.')
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc) if isinstance(exc,ValueError) else type(exc).__name__+': bootstrap/transport failure')
        finally:client.close()
        result.failed_spins=max(0,spins-result.successful_spins)
        write_paid_option_inventory(result,primitive={'id':'playson.xml.observed-test-base','version':1},source='Captured official TEST client contract; paid bindings unverified',options=[],complete=False,
            evidence_files=['bootstrap-summary.json'] if (folder/'bootstrap-summary.json').exists() else [],unresolved=['COMPLETE_PAID_OPTION_BINDINGS_AND_EXECUTIONS_REQUIRED'])
        result.error='; '.join(errors+['Complete paid-option inventory remains unverified.'])
        (folder/'result.json').write_text(json.dumps(result.to_dict(),indent=2),encoding='utf8');return result
