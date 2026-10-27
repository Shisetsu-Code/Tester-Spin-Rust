"""Observed Play'n GO practice registration + gamehub text-command family.

Execution requires a per-game, capture-bound base quote. No captured session is
ever reused. Only the observed settled base signature can certify a spin.
"""
import hashlib,json,re,shlex,time
from urllib.parse import urlsplit,parse_qs,urljoin
from curl_cffi import requests
import websocket
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.models import GameTestResult,SpinAttempt
from tester_spin.paid_options import write_paid_option_inventory

def _string(value):
    b=value.encode('utf8');n=len(b)
    if n<32:return bytes([0xa0+n])+b
    if n<256:return b'\xd9'+bytes([n])+b
    if n<65536:return b'\xda'+n.to_bytes(2,'big')+b
    raise ValueError('INVOCATION_SIZE_LIMIT')

def encode_invocation(payload):
    body=b'\x95\x01\x80\xc0'+_string('ProcessPacket')+b'\x91'+_string(payload)
    size=len(body);prefix=bytearray()
    while size>=128:prefix.append((size&127)|128);size>>=7
    prefix.append(size);return bytes(prefix)+body

def decode_invocation(data):
    if not isinstance(data,bytes) or not 2<=len(data)<=65540:raise ValueError('GAMEHUB_FRAME_LIMIT')
    size=0;pos=0
    for shift in (0,7,14,21):
        if pos>=len(data):raise ValueError('TRUNCATED_LENGTH')
        value=data[pos];pos+=1;size|=(value&127)<<shift
        if value<128:break
    else:raise ValueError('INVALID_LENGTH_PREFIX')
    if size!=len(data)-pos:raise ValueError('FRAME_LENGTH_MISMATCH')
    body=data[pos:]
    if body==b'\x91\x06':return {'kind':'ping'}
    if body[:4] not in (b'\x95\x01\x80\xc0',b'\x96\x01\x80\xc0'):raise ValueError('UNKNOWN_INVOCATION_ENVELOPE')
    cursor=4
    def read_string():
        nonlocal cursor
        if cursor>=len(body):raise ValueError('TRUNCATED_STRING')
        marker=body[cursor];cursor+=1
        if 0xa0<=marker<=0xbf:n=marker-0xa0
        elif marker in (0xd9,0xda):
            width=1 if marker==0xd9 else 2
            if cursor+width>len(body):raise ValueError('TRUNCATED_STRING_LENGTH')
            n=int.from_bytes(body[cursor:cursor+width],'big');cursor+=width
        else:raise ValueError('UNOBSERVED_ARGUMENT_TYPE')
        if cursor+n>len(body):raise ValueError('TRUNCATED_STRING_VALUE')
        value=body[cursor:cursor+n].decode('utf8');cursor+=n;return value
    target=read_string()
    if target not in ('ProcessPacket','Commands') or body[cursor:cursor+1]!=b'\x91':raise ValueError('UNOBSERVED_INVOCATION_TARGET')
    cursor+=1;payload=read_string()
    if body[cursor:]!=(b'\x90' if body[0]==0x96 else b''):raise ValueError('UNKNOWN_TRAILING_FIELDS')
    return {'kind':'invocation','target':target,'payload':payload}

def command_rows(text):
    if not isinstance(text,str) or len(text)>65536:raise ValueError('GAME_COMMAND_LIMIT')
    text=text.replace('\r\r\n','\n').replace('\r\n','\n')
    if not text.startswith('d='):raise ValueError('COMMAND_ENVELOPE_REQUIRED')
    rows=[]
    for line in text[2:].splitlines():
        if not line.strip():continue
        try:fields=shlex.split(line)
        except ValueError:raise ValueError('INVALID_COMMAND_QUOTING')
        if not fields or not fields[0].isdigit():raise ValueError('UNKNOWN_COMMAND_ROW')
        rows.append(fields)
    return rows

def http_body(sequence,session,command):
    if type(sequence) is not int or sequence<=0 or any(c in session for c in ('\r','\n')) or any(c in command for c in ('\r','\n','&')):
        raise ValueError('UNSAFE_HTTP_PACKET_FIELDS')
    return 'd='+str(sequence)+'\r\n'+session+'\r\n'+command+'\r\n'

def initialization_command(config,game_id):
    settings=config.get('settings','')
    if type(game_id) is not int or not settings.startswith('&settings=') or not re.fullmatch(r'[A-Za-z0-9%+_.\-]+',settings[10:]):
        raise ValueError('CURRENT_INITIALIZATION_SETTINGS_UNBOUND')
    return '104 '+str(game_id)+' 0 %22'+settings[10:]+'%22'

def verify_base_reply(text,*,before,command,cost):
    rows=command_rows(text);req=command.split();out=[r for r in rows if r[0]=='1'];states=[r for r in rows if r[0]=='3'];wins=[r for r in rows if r[0]=='6'];cash=[r for r in rows if r[0]=='52']
    if len(req)!=5 or req[0]!='1' or len(out)!=1 or out[0][1:4]!=req[1:4]:raise ValueError('SPIN_REPLY_CORRELATION_UNBOUND')
    if states!=[['3','0','0','0','0','1']] or len(wins)!=1 or len(wins[0])!=2 or len(cash)!=1 or len(cash[0])!=4 or cash[0][2:]!=['0','0']:
        raise ValueError('OBSERVED_SETTLED_BASE_SIGNATURE_REQUIRED')
    if not wins[0][1].isdigit() or not cash[0][1].isdigit() or int(cash[0][1])!=before-cost+int(wins[0][1]):raise ValueError('ROUND_LEDGER_MISMATCH')
    # Unknown stateful command additions cannot silently certify closure.
    if any(r[0] not in ('1','3','6','52') for r in rows):raise ValueError('ADDITIONAL_GAME_BRANCH_UNKNOWN')
    return True

def validate_profile(profile,game):
    if (profile.get('schema')!='playngo.observed-practice-base/v1' or profile.get('slug')!=game.slug
            or not re.fullmatch(r'[a-z0-9]+',profile.get('gid','')) or type(profile.get('game_id')) is not int
            or profile.get('practice')!=1 or profile.get('currency')!='DEMO'
            or not re.fullmatch(r'1 \d+ \d+ \d+ 1',profile.get('base_command',''))
            or type(profile.get('cost_minor')) is not int or profile['cost_minor']<=0
            or not re.fullmatch('[a-f0-9]{64}',profile.get('source_sha256',''))):raise ValueError('OBSERVED_BASE_PROFILE_UNBOUND')
    if profile['cost_minor']!=__import__('math').prod(int(x) for x in profile['base_command'].split()[1:4]):raise ValueError('OBSERVED_BASE_COST_MISMATCH')
    return True

class PlayNGoProvider(CatalogProvider):
    key='playngo';display_name="Play'n GO";catalog_url='https://www.playngo.com/games'
    execution_supported=True;max_test_concurrency=1

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        folder=self.game_dir(game)/'tests'/str(time.time_ns());folder.mkdir(parents=True)
        result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,0,'PARCIAL',symbol=game.symbol,run_dir=str(folder))
        client=requests.Session(impersonate='chrome');ws=None;errors=[];evidence=[];sequence=0;session=''
        def save(name,value):
            (folder/name).write_text(json.dumps(value,indent=2),encoding='utf8')
            if name not in evidence:evidence.append(name)
        def call(method,url,**kwargs):
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            save('phase.json',{'method':method,'host':urlsplit(url).hostname,'path':urlsplit(url).path})
            r=client.request(method,url,timeout=timeout_s,allow_redirects=False,**kwargs)
            if r.status_code!=200:raise ValueError('HTTP '+str(r.status_code)+' '+urlsplit(url).path)
            if len(r.content)>4*1024*1024:raise ValueError('BOOTSTRAP_LIMIT')
            return r
        try:
            source=self.game_dir(game)/'analysis/observed-practice-base.json'
            if not source.is_file():raise ValueError('CAPTURE_BOUND_PRACTICE_PROFILE_REQUIRED')
            profile=json.loads(source.read_text(encoding='utf8'));validate_profile(profile,game)
            meta=call('GET','https://released.playngonetwork.com/games/getgamebygid/'+profile['gid']).json()
            if meta.get('gameId')!=profile['game_id'] or meta.get('gId')!=profile['gid']:raise ValueError('OFFICIAL_GAME_ID_MISMATCH')
            pre=call('GET','https://released.playngonetwork.com/configuration/prelaunchconfiguration',params={'gameId':str(meta['gameId']),'language':'en_GB','productGroup':'2','practice':'1','channel':'desktop'}).json()
            server=pre.get('Server','');u=urlsplit(server)
            if u.scheme!='https' or u.hostname!='ascflyp.playngonetwork.com' or u.port not in (None,443) or u.username or u.password:raise ValueError('OBSERVED_PRACTICE_SERVER_UNBOUND')
            endpoint='https://ascflyp.playngonetwork.com/'
            headers={'Origin':'https://released.playngonetwork.com','Referer':'https://released.playngonetwork.com/','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'}
            def http_packet(command):
                nonlocal sequence,session
                sequence+=1;body=http_body(sequence,session or '0',command)
                response=call('POST',endpoint,headers=headers,data=body).text
                save('http-phase-summary.json',{'sequence':sequence,'response_bytes':len(response),'command_envelope':response.startswith('d='),'response_sha256':hashlib.sha256(response.encode()).hexdigest()})
                rows=command_rows(response)
                found=[r[1] for r in rows if r[0]=='103' and len(r)==2]
                if len(found)!=1:raise ValueError('FRESH_PRACTICE_SESSION_UNBOUND')
                session=found[0];return rows
            title=meta['name']
            if not isinstance(title,str) or any(c in title for c in ('"','\r','\n')):raise ValueError('REGISTRATION_TITLE_UNBOUND')
            http_packet('103 12 "en_GB" '+str(meta['gameId'])+' "Mozilla/5.0" '+json.dumps(title)+' "desktop"')
            login=http_packet('101 "" "" "" "" "" ""')
            users=[r for r in login if r[0]=='101']
            if len(users)!=1 or len(users[0])<5 or users[0][2]!='DEMO' or users[0][4]!='ZZ':raise ValueError('SERVER_PRACTICE_CURRENCY_REQUIRED')
            config=call('GET','https://released.playngonetwork.com/configuration/v2',params={'pid':'2','gameid':str(meta['gameId']),'lang':'en_GB','practice':'1','channel':'desktop','jurisdiction':'ZZ','platform':'megaton','currency':'DEMO','_r':str(time.time_ns())}).json()
            if config.get('defaultProtocol')!='ws':raise ValueError('OBSERVED_WS_CONFIGURATION_REQUIRED')
            ws=websocket.create_connection('wss://ascflyp.playngonetwork.com//gamehub',origin='https://released.playngonetwork.com',timeout=timeout_s)
            ws.send('{"protocol":"messagepack","version":1}\x1e')
            handshake=ws.recv()
            if isinstance(handshake,bytes):handshake=handshake.decode('utf8')
            if handshake.strip('\x1e\r\n ')!='{}':raise ValueError('GAMEHUB_HANDSHAKE_REJECTED')
            def exchange(command):
                nonlocal sequence
                sequence+=1;payload='d='+str(sequence)+'\r\n'+session+'\r\n'+command+'\r\n'
                ws.send_binary(encode_invocation(payload));deadline=time.monotonic()+timeout_s
                while time.monotonic()<deadline:
                    raw=ws.recv()
                    if not isinstance(raw,bytes):raise ValueError('UNOBSERVED_TEXT_GAME_REPLY')
                    decoded=decode_invocation(raw)
                    if decoded.get('kind')=='ping':continue
                    if decoded.get('target')!='Commands':raise ValueError('GAMEHUB_RESPONSE_TARGET_UNBOUND')
                    rows=command_rows(decoded['payload'])
                    if rows:return decoded['payload'],rows
                raise ValueError('GAME_REPLY_TIMEOUT_UNCERTAIN')
            initial,rows=exchange(initialization_command(config,meta['gameId']));cash=[r for r in rows if r[0]=='52'];denoms=[r for r in rows if r[0]=='54']
            if len(cash)!=1 or len(cash[0])!=4 or cash[0][2:]!=['0','0'] or not cash[0][1].isdigit() or len(denoms)!=1:
                raise ValueError('INITIAL_BALANCE_OR_DENOMINATIONS_UNBOUND')
            before=int(cash[0][1]);bet=profile['base_command'];args=bet.split();values=denoms[0][2:-1]
            if any(n not in values for n in args[2:4]) or before<profile['cost_minor']:raise ValueError('OBSERVED_QUOTE_NOT_IN_CURRENT_DOMAIN')
            save('bootstrap-summary.json',{'practice':1,'currency':'DEMO','game_id':meta['gameId'],'source_sha256':profile['source_sha256'],'balance_minor':before,'denomination_row':denoms[0],'observed_base_command':bet,'cost_minor':profile['cost_minor'],'inventory_complete':False})
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            attempt=SpinAttempt(1,False,mode_id='SPIN',mode_kind='SPIN',symbol=str(meta['gameId']),endpoint='wss://ascflyp.playngonetwork.com//gamehub');result.attempts.append(attempt)
            save('dispatch.json',{'state':'DISPATCHED_UNCERTAIN_UNTIL_VERIFIED','command':bet,'cost_minor':profile['cost_minor']})
            reply,rows=exchange(bet)
            # Only numeric game-result rows are persisted; session/user tokens
            # never leave the fresh in-memory registration.
            save('base-round.json',{'numeric_rows':[r for r in rows if all(re.fullmatch(r'\d+(?:\.\d+)?',v) for v in r)]})
            verify_base_reply(reply,before=before,command=bet,cost=profile['cost_minor'])
            attempt.ok=True;attempt.terminal=True;attempt.status_code=101;attempt.wire_steps=1;result.successful_spins=1
            result.structural_map['playngo_gamehub']={'practice':1,'currency':'DEMO','closed_base_rounds':1,'inventory_complete':False}
            progress('Playn GO: fresh practice registration + gamehub spin closed with captured base signature and reconciled balance.')
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc) if isinstance(exc,(ValueError,KeyError)) else type(exc).__name__+': bootstrap/transport failure')
        finally:
            if ws is not None:
                try:ws.close()
                except Exception:pass
            client.close()
        result.failed_spins=max(0,spins-result.successful_spins)
        write_paid_option_inventory(result,primitive={'id':'playngo.gamehub.observed-practice-base','version':1},source='Fresh official practice session; complete paid inventory unknown',options=[],complete=False,evidence_files=evidence,
            unresolved=['COMPLETE_PAID_INVENTORY','BONUS_BRANCH_CONTINUATIONS'])
        result.error='; '.join(errors+['Complete paid-option inventory remains unverified.'])
        save('result.json',result.to_dict());return result
