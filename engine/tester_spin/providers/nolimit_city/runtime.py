"""Fresh demo transport and money-checked primitives from the captured NLC SDK."""
from __future__ import annotations
import hashlib,json,re,time,uuid
from decimal import Decimal,ROUND_HALF_UP
from select import select
from curl_cffi import CurlError
from curl_cffi.const import CurlECode,CurlInfo,CurlWsFlag
from .protocol import rc4_hex,lzw_decode,websocket_url,_money,_closed,MAX_BODY

API='https://demo.nolimitcity.com/EjsFrontWeb/fs'
CDN='https://demo.nolimitcdn.com/games/'
PROTOCOL='@nolimitcity/game-communication@0.4.1'
MONETARY='nolimit-city/round-ledger/v1'

from .errors import Unlearned
from .client_identity import validate_client_info

def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def sanitized(data):
    if isinstance(data,list):return [sanitized(v) for v in data]
    if isinstance(data,dict):return {k:sanitized(v) for k,v in data.items() if k not in {'extPlayerKey','playerConnect','key','token','tokenString'}}
    return data

class NolimitSession:
    def __init__(self):
        self.direct_demo_transport=False
        self.automatic_actions={}
        self.socket=None;self.rows=[];self.capture=None;self.remembered={};self.counter=0;self.uuid=uuid.uuid4().hex;self.choice_domains={};self.pending_choice=None;self.choice_client=None;self.pending_automatic=None;self.pending_contract=None;self.extra_round=None;self.pending_repeat_reason=None
    def open(self,game,http,timeout,stop,directory):
        self.direct_demo_transport=False
        self.timeout=max(.1,float(timeout));self.stop=stop
        response=http.get(CDN+game.symbol+'/info.json',timeout=self.timeout);response.raise_for_status()
        info=validate_client_info(response.json(),game.symbol);version=info['version']
        self.client_info=info;self.http=http;self.choice_root=directory
        self.client_cache=directory.parents[3]/'_clients'/info['name']/(version+'.js')
        save(directory/'client-info.json',info)
        payload={'action':'open_game','clientString':'FANPAGE_DEMO','language':'en','gameCodeString':game.symbol+'@desktop'}
        save(directory/'bootstrap-request.json',payload)
        response=http.post(API,data=payload,headers={'Origin':'https://playin.com'},timeout=self.timeout);response.raise_for_status()
        config=response.json()
        if not isinstance(config,dict) or not isinstance(config.get('key'),str):raise Unlearned('Nolimit City: servidor no abrió la Demo')
        self.key=config['key'];target=websocket_url(config.get('url',''),self.key)
        self.target=target
        self.capture={'log':{'version':'1.2','creator':{'name':'Tester-Spin','version':'nolimit-runtime-v1'},
            'entries':[{'request':{'method':'POST','url':API,'postData':{'mimeType':'application/x-www-form-urlencoded','text':'&'.join(k+'='+v for k,v in payload.items())}},
                'response':{'status':response.status_code,'content':{'mimeType':'application/json','text':json.dumps(config)}}}],
            '_warpWebSockets':self.rows}}
        self.capture_path=directory.parent/'capture.har'
        self.socket=http.ws_connect(target,headers={'Origin':'https://playin.com'},timeout=self.timeout)
        reply=self._exchange({'type':'init'},directory,version=version)
        if reply.get('init')!='ok':raise Unlearned('Nolimit City: inicialización no confirmada')
        try:require_idle_initial_state(reply)
        except ValueError:pass # Keep declarations available; the adapter still rejects non-fresh sessions.
        else:self.direct_demo_transport=True
        return reply
    def _receive(self):
        deadline=time.monotonic()+self.timeout;parts=[];size=0
        while time.monotonic()<deadline:
            if self.stop.is_set():raise Unlearned('Nolimit City: ejecución detenida')
            try:
                chunk,frame=self.socket.recv_fragment()
            except CurlError as exc:
                if exc.code!=CurlECode.AGAIN:raise
                select([self.socket.curl.getinfo(CurlInfo.ACTIVESOCKET)],[],[],min(.1,max(0,deadline-time.monotonic())))
                continue
            if frame.flags & CurlWsFlag.CLOSE:raise Unlearned('Nolimit City: servidor cerró la conexión')
            if frame.flags & (CurlWsFlag.PING|CurlWsFlag.PONG):continue
            size+=len(chunk)
            if size>MAX_BODY:raise Unlearned('Nolimit City: respuesta excede el límite')
            parts.append(chunk)
            if frame.bytesleft==0 and not frame.flags & CurlWsFlag.CONT:
                if not frame.flags & CurlWsFlag.TEXT:raise Unlearned('Nolimit City: trama de formato desconocido')
                return b''.join(parts).decode('utf-8')
        raise TimeoutError('Nolimit City: tiempo de respuesta agotado; no se reenvía una apuesta incierta')
    def _exchange(self,content,directory,version=None):
        if self.stop.is_set():raise Unlearned('Nolimit City: ejecución detenida')
        self.counter+=1
        request={'type':'init' if version else 'normal','content':content,'protocol':PROTOCOL,
                 'id':self.uuid+'-'+str(self.counter),'data':self.remembered.copy()}
        if version:request['gameClientVersion']=version
        save(directory/f'{self.counter:04d}.request.json',sanitized(request))
        plaintext=json.dumps(request,separators=(',',':'),ensure_ascii=True)
        encrypted=rc4_hex(self.key,plaintext.encode('latin1').hex()).encode('latin1').hex()
        self.rows.append({'url':self.target,'direction':'sent','timestamp':time.time(),'payload':encrypted,'encoding':'utf8'})
        self.socket.send(encrypted,flags=CurlWsFlag.TEXT)
        raw=self._receive()
        self.rows.append({'url':self.target,'direction':'received','timestamp':time.time(),'payload':raw,'encoding':'utf8'})
        answer=json.loads(lzw_decode(raw))
        save(directory/f'{self.counter:04d}.response.json',sanitized(answer))
        if not isinstance(answer,dict) or answer.get('id')!=request['id']:raise Unlearned('Nolimit City: respuesta no corresponde a la petición')
        if answer.get('error'):raise Unlearned('Nolimit City: servidor rechazó la operación')
        ext=answer.get('extPlayerKey')
        if ext is not None:
            if not isinstance(ext,str) or not ext:raise Unlearned('Nolimit City: continuidad de sesión inválida')
            self.remembered={'extPlayerKey':ext}
        return answer
    def exchange(self,content,directory):return self._exchange(content,directory)
    def _load_choice_client(self):
        if self.choice_client is not None:return
        info=self.client_info
        target=CDN+info['name']+'/'+info['version']+'/game.js'
        cache=getattr(self,'client_cache',None)
        if cache is not None and cache.is_file() and cache.stat().st_size<=MAX_BODY:
            self.choice_client=cache.read_text(encoding='utf-8');return
        response=self.http.get(target,timeout=self.timeout);response.raise_for_status()
        if len(response.content)>MAX_BODY:raise Unlearned('Nolimit City: cliente excede el limite de descubrimiento')
        self.choice_client=response.text
        if cache is not None:
            cache.parent.mkdir(parents=True,exist_ok=True);cache.write_text(self.choice_client,encoding='utf-8')

    def next_command(self,answer,directory,root_id,mode=None,*,raw_answer=None):
        from .contracts import resolve_operation
        try:contract=resolve_operation(answer,mode,raw_answer=raw_answer,client_source=self.choice_client,direct_demo_transport=self.direct_demo_transport)
        except Unlearned:
            self._load_choice_client()
            contract=resolve_operation(answer,mode,raw_answer=raw_answer,client_source=self.choice_client,direct_demo_transport=self.direct_demo_transport)
        self.pending_contract=contract
        save(directory/f'operation-{self.counter:04d}.json',contract)
        if contract['domain'] is None:
            self.pending_automatic=(root_id,contract['state'])
            save(directory/'automatic-action.json',{'schema':'nolimit-client-bound-zero-bet/v1',
                'state':contract['state'],'request':contract['request'],**contract['evidence']})
            return contract['request']
        domain=contract['domain'];key=(root_id,domain['state']);known=self.choice_domains.get(key)
        if known is None:
            known={**domain,'covered':[]};self.choice_domains[key]=known
        elif known['options']!=domain['options'] or known['ack_field']!=domain['ack_field']:
            raise Unlearned('Nolimit City: dominio de eleccion cambio durante la prueba')
        from tester_spin.providers.repeat_purchase import POLICY,choose_repeat,new_probe
        self.pending_repeat_reason=None
        if domain.get('repeat_purchase_policy')==POLICY:
            if self.extra_round is None or self.extra_round['root']!=root_id:self.begin_round(root_id)
            first_offer=key not in self.extra_round['keys']
            self.extra_round['keys'].add(key)
            if 'repeat_purchase_probe' not in known:known['repeat_purchase_probe']=new_probe()
            if first_offer:known['repeat_purchase_probe'].update(status='PENDING',terminal_reason=None)
            for field in ('repeat_purchase_policy','funding_source','funding_balance','quoted_price','accept_option','decline_option'):
                known[field]=domain[field]
            selected,self.pending_repeat_reason=choose_repeat(domain,known['covered'])
        else:
            selected=next((option for option in domain['available'] if option not in known['covered']),domain['available'][0])
        self.pending_choice=(domain,selected,key)
        save(directory/'choice-domain.json',{**domain,'selected':selected,'root_mode':root_id,'selection_reason':self.pending_repeat_reason})
        return {'type':domain.get('request_type','zeroBet'),'bet':'0.00','playerInteraction':{
            domain.get('request_field','selectedIndex'):selected if domain.get('request_field')=='gambleCollected' or domain.get('wire_encoding')=='PRESERVE_LITERAL' else str(selected)}}

    def choice_command(self,answer,directory,root_id):
        # Compatibility entry point; both paths use the same operation planner.
        return self.next_command(answer,directory,root_id)

    def confirm_pending_choice(self,answer):
        if self.pending_contract is None:return
        from .contracts import confirm_operation
        selected=self.pending_choice[1] if self.pending_choice is not None else None
        confirm_operation(self.pending_contract,answer,selected)
        if self.pending_automatic is not None and (self.pending_contract.get('evidence') or {}).get('client_sha256'):
            encoded=json.dumps(self.pending_contract,sort_keys=True)
            self.automatic_actions[(self.pending_automatic[0],encoded)]=json.loads(encoded)
        if self.pending_choice is not None:
            domain,selected,key=self.pending_choice
            covered=self.choice_domains[key]['covered']
            if selected not in covered:covered.append(selected)
            known=self.choice_domains[key]
            probe=known.get('repeat_purchase_probe')
            if probe is not None:
                if selected==domain['accept_option']:
                    probe['accepted_purchases']+=1
                    probe['spent']=str(Decimal(probe['spent'])+_money(domain['quoted_price'],positive=True))
                    self.extra_round['accepted'][key]=self.extra_round['accepted'].get(key,0)+1
                elif self.pending_repeat_reason=='INSUFFICIENT_PENDING_PRIZE':
                    self.extra_round['insufficient'].add(key)

        self.pending_choice=None;self.pending_automatic=None;self.pending_contract=None
    def begin_round(self,root_id):
        self.extra_round={'root':root_id,'keys':set(),'accepted':{},'insufficient':set()}
    def finish_round(self,root_id):
        # The adapter calls this only after monetary reconciliation and a normal
        # settled state. An acknowledged choice alone cannot complete this probe.
        current=self.extra_round
        if current is None or current['root']!=root_id:return
        for key in current['keys']:
            probe=self.choice_domains[key]['repeat_purchase_probe']
            reason=('INSUFFICIENT_PENDING_PRIZE' if key in current['insufficient'] else
                'SERVER_CLOSED_ROUND' if current['accepted'].get(key,0)>0 else None)
            if reason is not None:probe.update(status='COMPLETE',terminal_reason=reason)
        self.extra_round=None
    def sync_choices(self,mode):
        mode['automatic_actions']=[json.loads(json.dumps(contract)) for (root_id,_),contract in self.automatic_actions.items() if root_id==mode['id']]
        mode['choice_domains']=[{k:v for k,v in domain.items() if k not in ('available','before')}
            for (root_id,state),domain in self.choice_domains.items() if root_id==mode['id']]
        from tester_spin.providers.repeat_purchase import repeat_complete
        return all(set(domain['options'])<=set(domain['covered']) and repeat_complete(domain) for domain in mode['choice_domains'])
    def close(self):
        if self.capture is not None:save(self.capture_path,self.capture)
        if self.socket is not None:
            try:self.socket.close()
            except Exception:pass

def _boosted_response(game):
    return (all(key in game for key in ('boostedBet','wasFeatureBuy','playedBetValue',
        'accumulatedRoundWin','mode','nextMode','freespinsLeft','freespinsPlayed'))
        and ('win' in game or 'totalSpinWinnings' in game))


from .operation_fields import row_response as _row_response

def _level_response(game):
    fields=('totalSpinWinnings','accumulatedRoundWin','playedBetValue','mode','nextMode',
        'numberOfFreespinsPlayed','freespinsLeft','freespinTriggeredThisSpin','wasFeatureBuy',
        'collapsedReel','collectedWinningSymbols','previousLevel','currentLevel','isRandomLevel')
    return (all(key in game for key in fields) and isinstance(game['collapsedReel'],list)
        and all(type(game[key]) is bool for key in ('freespinTriggeredThisSpin','wasFeatureBuy','isRandomLevel'))
        and all(type(game[key]) is int and game[key]>=0 for key in ('numberOfFreespinsPlayed','freespinsLeft','collectedWinningSymbols','previousLevel','currentLevel'))
        and not any(key in game for key in ('boostedBet','boostedBetPlayed','enhancedBet','extraSpinCost','isExtraSpin')))

def _extra_response(game):
    return (_boosted_response(game) and type(game.get('isExtraSpin')) is bool
        and type(game.get('isSuperFreespins')) is bool)

def _category_response(game):
    return (all(key in game for key in ('featureBet','numberOfFreespinsPlayed',
        'totalSpinWinnings','freespinTriggeredThisSpin','wasFeatureBuy','playedBetValue',
        'accumulatedRoundWin','mode','nextMode','freespinsLeft'))
        and (game['featureBet'] is False or (game['featureBet'] is True and game['wasFeatureBuy'] is True
            and game['mode']=='NORMAL' and game['numberOfFreespinsPlayed']==0)))


def _batch_response(game):
    core=all(key in game for key in ('wasFeatureBuy','playedBetValue','accumulatedRoundWin',
        'totalSpinWinnings','mode','nextMode','freespinsLeft'))
    counter=any(type(game.get(key)) is int and game[key]>=0
        for key in ('freespinsPlayed','freeSpinsPlayed','numberOfFreespinsPlayed'))
    marker=any(type(game.get(key)) is bool for key in ('boostedBet','boostedBetPlayed','enhancedBet'))
    numeric_enhanced=type(game.get('enhancedBet')) is int and game['enhancedBet']>=0
    return core and counter and (marker or numeric_enhanced)


def _pending_auto_phase(answer,game,*,explicit_no_extra=False):
    next_mode=game.get('nextMode');left=game.get('freespinsLeft',answer.get('remainingFreeSpins'))
    if (next_mode=='STACKED_RESPIN_FREESPIN' and answer.get('pendingWin') is True
            and game.get('stackedSpinTriggered') is True and type(left) is int and left>0):return True
    state_shape=any(isinstance(game.get(key),list) and game[key]
        for key in ('reelsAfterCollapse','reelsAfterAvalanche','symbolsAfterTumbleForClient','collapsedReel'))
    if not state_shape:return False
    respins={'NORMAL_AVALANCHE_RESPIN','FREESPIN_AVALANCHE_RESPIN','SUPER_FREESPIN_AVALANCHE_RESPIN'}
    if next_mode in respins:
        if not explicit_no_extra or game.get('wasExtraSpin') is not False:return False
        try:return _money(game.get('extraSpinCost'))==0
        except ValueError:return False
    avalanche=next_mode in {'NORMAL_AVALANCHE','FREESPIN_AVALANCHE','SUPER_FREESPIN_AVALANCHE',
        'AVALANCHE_NORMAL','AVALANCHE_FREESPIN','AVALANCHE_FREESPIN_SUPER'}
    if not avalanche or answer.get('pendingWin') is not True:return False
    try:return _money(game.get('win'))>0
    except ValueError:return False


def require_idle_initial_state(init):
    from .state import initial_state
    try:initial_state(init)
    except ValueError as exc:raise Unlearned(str(exc)) from exc


def declaration(init, *, require_idle=True):
    from .declarations import declared_options
    modes,domains=declared_options(init)
    if require_idle:require_idle_initial_state(init)
    return modes,domains


def normalized_response(answer, declared_options=(), declared_categories=(),declared_purchase_options=(),*,declared_catalog=None,declared_game_modes=(),allow_unresolved_state=False,client_source=None,declared_modifier_selector=None,counter_source=None):
    """Normalize proven server fields without treating catalog entries as choices."""
    answer=dict(answer);game=dict(answer.get('game') or {})
    from .client_counters import counter_contract,counter_from_contract
    counter_proof=counter_contract(counter_source if counter_source is not None else client_source)
    if counter_proof is not None and counter_proof['field'] in game:
        game['freespinsLeft']=counter_from_contract(answer,counter_proof)
    elif 'freespinsLeft' not in game and 'freespinsRemaining' in game:
        from .operation_fields import remaining_alias
        game['freespinsLeft']=remaining_alias(answer)
    if type(game.get('featureBuy')) is bool:
        if 'wasFeatureBuy' in game and game['wasFeatureBuy'] is not game['featureBuy']:
            raise ValueError('Nolimit City: acuses de compra contradictorios')
        game['wasFeatureBuy']=game['featureBuy']
    explicit_no_extra=game.get('wasExtraSpin') is False
    legacy=all(key in game for key in ('thisSpinWinning','totalSpinWinnings','enhancedBet','featureName','firstStage','secondStage','secondStageFsLeft'))
    if legacy:
        if type(game['enhancedBet']) is not bool:raise Unlearned('Nolimit City: indicador enhancedBet inválido')
        if 'wasBoostedBet' in game and game['wasBoostedBet'] is not game['enhancedBet']:
            raise ValueError('Nolimit City: indicadores de apuesta mejorada contradictorios')
        game['wasBoostedBet']=game['enhancedBet']
        if 'wasExtraSpin' not in game:game['wasExtraSpin']=False
        if 'win' in game and _money(game['win'])!=_money(game['thisSpinWinning']):
            raise ValueError('Nolimit City: indicadores de premio contradictorios')
        game['win']=game['thisSpinWinning']
    boosted_dialect=_boosted_response(game)
    category_dialect=_category_response(game)
    if boosted_dialect:
        if type(game['boostedBet']) is not bool:raise Unlearned('Nolimit City: indicador boostedBet inválido')
        if 'wasBoostedBet' in game and game['wasBoostedBet'] is not game['boostedBet']:
            raise ValueError('Nolimit City: indicadores de apuesta mejorada contradictorios')
        game['wasBoostedBet']=game['boostedBet']
    elif category_dialect:
        if 'wasBoostedBet' in game and game['wasBoostedBet'] is not False:
            raise ValueError('Nolimit City: indicadores de apuesta mejorada contradictorios')
        game['wasBoostedBet']=False
    if boosted_dialect or category_dialect:
        # All normal/feature/zeroBet steps of these captured dialects omit this
        # optional acknowledgment. Explicit extra spins remain unsupported.
        if 'wasExtraSpin' not in game:game['wasExtraSpin']=False
        if 'totalSpinWinnings' in game and not _batch_response(game):
            if 'win' in game and _money(game['win'])!=_money(game['totalSpinWinnings']):
                raise ValueError('Nolimit City: indicadores de premio contradictorios')
            game['win']=game['totalSpinWinnings']
        if game.get('nextMode')=='NORMAL' and game.get('respinsLeft',0)!=0:
            raise Unlearned('Nolimit City: respin todavía pendiente')
    batch_dialect=_batch_response(game)
    if batch_dialect:
        flags=[]
        for key in ('boostedBet','boostedBetPlayed','enhancedBet'):
            if key not in game:continue
            value=game[key]
            if type(value) is bool:flags.append(value)
            elif key=='enhancedBet' and type(value) is int and value>=0:flags.append(value>0)
            else:raise Unlearned('Nolimit City: indicador de apuesta mejorada inválido: '+key)
        if len(set(flags))!=1 or ('wasBoostedBet' in game and game['wasBoostedBet'] is not flags[0]):
            raise ValueError('Nolimit City: indicadores de apuesta mejorada contradictorios')
        game['wasBoostedBet']=flags[0]
        if 'wasExtraSpin' not in game:game['wasExtraSpin']=False
        step=game.get('thisSpinWinning',game.get('thisSpinWinnings',game['totalSpinWinnings']))
        if 'win' in game and _money(game['win'])!=_money(step):
            raise ValueError('Nolimit City: indicadores de premio contradictorios')
        game['win']=step
    if _extra_response(game):
        if 'wasExtraSpin' in (answer.get('game') or {}) and answer['game']['wasExtraSpin'] is not game['isExtraSpin']:
            raise ValueError('Nolimit City: indicadores de extra spin contradictorios')
        game['wasExtraSpin']=game['isExtraSpin']
    if _level_response(game):
        if game.get('nextMode')=='NORMAL':
            for key in ('respinsLeft','secondStageFsLeft'):
                if key in game and (type(game[key]) is not int or game[key]!=0):
                    raise Unlearned('Nolimit City: contador pendiente o desconocido: '+key)
        if game.get('wasBoostedBet',False) is not False or game.get('wasExtraSpin',False) is not False:
            raise Unlearned('Nolimit City: modificador incompatible con perfil avalanche')
        game['wasBoostedBet']=False;game['wasExtraSpin']=False
        if 'win' in game and _money(game['win'])!=_money(game['totalSpinWinnings']):
            raise ValueError('Nolimit City: premios contradictorios')
        game['win']=game['totalSpinWinnings']
    if _row_response(game):
        if type(game.get('featureBet')) is not bool or not isinstance(game.get('gambleOptions'),dict):
            raise Unlearned('Nolimit City: perfil de filas incompleto')
        boosted=(game['featureBet'] or game['playedRowsInBase']>3) and not game['wasFeatureBuy']
        if 'wasBoostedBet' in game and game['wasBoostedBet'] is not boosted:
            raise ValueError('Nolimit City: indicadores de filas mejoradas contradictorios')
        if game.get('wasExtraSpin',False) is not False or game.get('extraSpinCost',0)!=0:
            raise Unlearned('Nolimit City: extra spin no aprendido en perfil de filas')
        for key in ('respinsLeft','secondStageFsLeft'):
            if key in game and (type(game[key]) is not int or game[key]!=0):raise Unlearned('Nolimit City: contador desconocido en perfil de filas')
        game['wasBoostedBet']=boosted;game['wasExtraSpin']=False
        if 'win' in game and _money(game['win'])!=_money(game.get('totalSpinWinnings')):
            raise ValueError('Nolimit City: premios contradictorios en perfil de filas')
        game['win']=game['totalSpinWinnings']
        row_features=answer.get('features')
        if isinstance(row_features,dict) and row_features.get('active','') in ('','FREESPIN') and row_features.get('available')==['FREESPIN']:
            answer['features']={**row_features,'available':[]}
            if row_features.get('active')=='FREESPIN':answer['features']['active']=''
    if declared_catalog is not None:
        from .state import feature_observation
        observation=feature_observation({**answer,'game':game},declared_catalog,declared_game_modes,declared_purchase_options,(declared_options,declared_purchase_options,declared_categories))
        answer['feature_observation']=observation
        if observation['kind'] in ('UNRESOLVED_MENU','UNRESOLVED_PHASE') and not allow_unresolved_state:
            raise Unlearned('Nolimit City: estado de función no resuelto: '+json.dumps(observation,ensure_ascii=True))
        if observation['kind'] in ('NONE','CATALOG','PHASE'):
            answer['features']={**answer['features'],'available':[],'active':''}
    from .operation_fields import step_win,modifier_ack,round_win
    from .client_money import monetary_fields
    client_money=(client_source is not None and 'win' not in game and monetary_fields(client_source) is not None)
    if client_money:
        game['win']=step_win(answer.get('game') or {},client_source=client_source)
        game['accumulatedRoundWin']=round_win(answer.get('game') or {},client_source=client_source)
        # These raw base components are not aliases of the client-selected total.
        # Preserve them in the raw response; the derived view has one canonical win.
        for field in ('thisSpinWinning','thisSpinWinnings','thisAvalancheWinnings'):
            game.pop(field,None)
    elif (any(key in game for key in ('win','thisSpinWinning','thisSpinWinnings','thisAvalancheWinnings'))
            or legacy or boosted_dialect or category_dialect or batch_dialect or _row_response(game) or _level_response(game)):
        game['win']=step_win(game)
    for key in ('isExtraSpin','wasExtraSpin'):
        if key in game and type(game[key]) is not bool:raise Unlearned('Nolimit City: acuse extra spin inválido')
    if 'isExtraSpin' in game:
        if 'wasExtraSpin' in (answer.get('game') or {}) and answer['game']['wasExtraSpin'] is not game['isExtraSpin']:
            raise ValueError('Nolimit City: acuses extra spin contradictorios')
        game['wasExtraSpin']=game['isExtraSpin']
    ack=modifier_ack(game,declared_selector=declared_modifier_selector)
    if ack is not None:game['wasBoostedBet']=ack
    if isinstance(game.get('boostedBetPlayed'),str) and ack is True:
        game.pop('boostedBetPlayed') # Canonical boolean; the original response retains its selector.
    features=answer.get('features')
    if (batch_dialect or category_dialect or _extra_response(game) or _level_response(game)) and isinstance(features,dict):
        active=features.get('active','')
        free_modes={'FREESPIN','SUPER_FREESPIN','FREESPIN_SUPER','FREESPIN_BETTER','FREESPIN_AVALANCHE','SUPER_FREESPIN_AVALANCHE'}
        active_free=(((active in free_modes and (active in declared_options or (declared_purchase_options and active==game.get('nextMode'))))
                or (category_dialect and active=='FREESPINS'))
            and (game.get('nextMode') in free_modes or (game.get('mode') in free_modes
                and game.get('nextMode')=='NORMAL' and game.get('freespinsLeft')==0)))
        active_auto=active in ('STACKED_RESPIN_FS','RESPIN') and _pending_auto_phase(answer,game,explicit_no_extra=explicit_no_extra)
        level_free=(_level_response(game) and active in ('FREESPIN','FREESPIN_SUPER')
            and (game.get('nextMode')==active or (game.get('mode')==active and game.get('nextMode')=='NORMAL')))
        level_root=(_level_response(game) and active in declared_purchase_options and game['wasFeatureBuy'] is True
            and game['mode']=='NORMAL' and game['freespinTriggeredThisSpin'] is True
            and game['numberOfFreespinsPlayed']==0 and game['freespinsLeft']>0
            and game['nextMode'] in ('FREESPIN','FREESPIN_SUPER'))
        level_auto=(_level_response(game) and active==game.get('nextMode') and _pending_auto_phase(answer,game))
        if active not in ('',None) and not (active_free or active_auto or level_free or level_root or level_auto) and not allow_unresolved_state:
            raise Unlearned('Nolimit City: función activa sin primitiva aprendida: '+str(active))
        if 'available' not in features:
            answer['features']={**features,'available':[]}
        else:
            items=features['available']
            if (isinstance(items,list) and items and all(isinstance(item,str) for item in items)
                    and len(items)==len(set(items)) and (set(items)==set(declared_options)
                    or (declared_categories and set(items)==set(declared_categories))
                    or (declared_purchase_options and set(items)==set(declared_purchase_options)))):
                answer['features']={**features,'available':[]}
    available=(answer.get('features') or {}).get('available')
    if (legacy and available and isinstance(available,list) and declared_options
            and all(isinstance(item,str) for item in available)
            and len(available)==len(set(available))
            and set(available)==set(declared_options)):
        # Exact init-advertised purchase/boost catalog, not a stage choice domain.
        answer['features']={**answer.get('features',{}),'available':[]}
    if category_dialect and available==['FREESPINS']:
        answer['features']={**answer.get('features',{}),'available':[]}
    if (answer.get('features') or {}).get('available')!=[] and not allow_unresolved_state:
        raise Unlearned('Nolimit City: elección sin primitiva aprendida: '+json.dumps(available,ensure_ascii=True))
    if legacy and game.get('nextMode')=='NORMAL' and game['secondStageFsLeft']!=0:
        raise Unlearned('Nolimit City: segunda etapa todavía pendiente')
    answer['game']=game
    return answer

class RoundLedger:
    def __init__(self,before,mode):
        self.before=_money(before);self.mode=mode;self.stake=_money(mode['stake'],positive=True)
        self.cost=(self.stake*_money(mode['price_multiplier'],positive=True)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        if self.cost>self.before:raise Unlearned('Nolimit City: saldo Demo insuficiente para la opción declarada')
        self.win=Decimal(0);self.steps=0;self.after=self.before;self.closed=False;self.had_feature=False;self.previous=None;self.extra_played=False;self.extra_cost=Decimal(0);self.root_ack_basis=None;self.numeric_extra_played=False
    def accept(self,answer,request=None,*,operation=None,client_source=None):
        raw_answer=answer;raw_game=answer.get('game') or {}
        from .client_money import monetary_fields
        source_candidate=(client_source is not None and 'win' not in raw_game and monetary_fields(client_source) is not None)
        normalize_options=dict(declared_catalog=self.mode.get('declared_feature_catalog'),declared_game_modes=self.mode.get('declared_game_modes',()),allow_unresolved_state=isinstance(request,dict),counter_source=client_source)
        if (self.mode['kind']=='FEATURE_SPIN' and self.mode.get('server_declared') is True
                and self.mode.get('selector') in self.mode.get('declared_feature_options',())
                and self.mode.get('server_type') in ('BOOSTED_BET','BOOSTED_BET_X_ROWS')):
            normalize_options['declared_modifier_selector']=self.mode['selector']
        declaration_args=(self.mode.get('declared_feature_options',()),self.mode.get('declared_feature_categories',()),self.mode.get('declared_purchase_options',()))
        answer=normalized_response(raw_answer,*declaration_args,**normalize_options)
        client_money=False
        if source_candidate:
            # A panel getter can summarize a subround. Never replace a step
            # whose explicit amount already reconciles with the round total.
            standard=answer.get('game') or {}
            try:
                if 'win' in standard:standard_delta=Decimal(str(standard['win']))
                else:
                    from .operation_fields import reconciled_step_win
                    standard_delta=Decimal(reconciled_step_win(standard,self.win))
                standard_valid=(standard_delta.is_finite() and self.win+standard_delta==_money(standard.get('accumulatedRoundWin')))
            except (ValueError,ArithmeticError):standard_valid=False
            if not standard_valid:
                answer=normalized_response(raw_answer,*declaration_args,**normalize_options,client_source=client_source)
                client_money=True
        answer.pop('_funded_extra_spin',None);answer.pop('_verified_numeric_extra_context',None)
        game=answer.get('game')
        if not isinstance(game,dict):raise Unlearned('Nolimit City: falta estado de juego')
        if client_money:
            from .operation_fields import reconciled_step_win
            if not isinstance(request,dict) or request.get('type') not in ('normalBet','featureBet','zeroBet','gambleBet'):
                raise Unlearned('Nolimit City: total monetario sin peticion contrastada')
            game['win']=reconciled_step_win(raw_game,self.win,client_source=client_source)
        elif 'win' not in game and 'totalSpinWinnings' in game:
            if not isinstance(request,dict) or request.get('type') not in ('normalBet','featureBet','zeroBet','gambleBet'):
                raise Unlearned('Nolimit City: total monetario sin petición contrastada')
            from .operation_fields import reconciled_step_win
            game['win']=reconciled_step_win(game,self.win)
        for field in ('win','accumulatedRoundWin','playedBetValue'):
            if (field!='playedBetValue' or self.steps==0) and game.get(field) is None:
                raise Unlearned('Nolimit City: campo monetario sin primitiva: '+field)
        if self.steps==0:
            if _money(game.get('playedBetValue'))!=self.stake:raise ValueError('Nolimit City: apuesta base no coincide')
        delta=None
        previous=self.previous or {}
        from .operation_fields import collect_available
        if collect_available(previous):
            if ((request or {}).get('type')!='gambleBet' or _money((request or {}).get('bet'))!=0
                    or (request or {}).get('playerInteraction')!={'gambleCollected':True}
                    or game.get('mode')!='GAMBLE' or game.get('nextMode')!='NORMAL'
                    or game.get('gambleCollect') is not True or _money(game.get('win'))!=0):
                raise Unlearned('Nolimit City: cobro sin petición y acuse contrastados')
        if _extra_response(previous) and previous.get('nextMode')=='EXTRA_SPIN':
            interaction=(request or {}).get('playerInteraction') or {}
            selected=interaction.get('playExtraSpin')
            if (request or {}).get('type')!='zeroBet' or _money((request or {}).get('bet'))!=0 or set(interaction)!={'playExtraSpin'} or selected not in ('yes','no'):
                raise Unlearned('Nolimit City: decisión extra spin sin petición contrastada')
            price=_money(previous.get('extraSpinCost'),positive=True)
            if not _extra_response(game) or game.get('mode')!='EXTRA_SPIN' or _money(game.get('extraSpinCost'),positive=True)!=price:
                raise Unlearned('Nolimit City: precio o transición extra spin no confirmado')
            if selected=='yes':
                if self.win<price or game.get('isExtraSpin') is not True or game.get('nextMode')!='FREESPIN' or game.get('freespinsLeft')!=1 or Decimal(str(game.get('win')))!=-price:
                    raise ValueError('Nolimit City: descuento del giro extra no coincide con la cotización')
                delta=-price;self.extra_cost+=price;self.extra_played=True
            elif game.get('nextMode')!='NORMAL' or _money(game.get('win'))!=0:
                raise ValueError('Nolimit City: rechazo extra spin sin liquidación')
        if isinstance(operation,dict) and operation.get('family') in ('QUOTED_NUMERIC_EXTRA','QUOTED_LITERAL_EXTRA'):
            from .contracts import observed_request_matches,confirm_operation
            domain=operation['domain'];matches,selected=observed_request_matches(operation,request or {})
            if (not matches or not (operation.get('evidence') or {}).get('client_sha256') or previous.get('nextMode')!='EXTRA_SPIN'
                    or _money(previous.get('extraSpinCost'),positive=True)!=_money(domain['quoted_price'])
                    or _money(domain['quoted_accumulated'])!=self.win):
                raise Unlearned('Nolimit City: giro extra fuera de su cotización actual')
            # A legacy normalizer may supply a default false flag. Receipts
            # must distinguish that derived default from an explicit wire ACK.
            receipt_answer=answer
            if not any(key in raw_game for key in ('isExtraSpin','wasExtraSpin')):
                receipt_game=dict(game)
                receipt_game.pop('isExtraSpin',None);receipt_game.pop('wasExtraSpin',None)
                receipt_answer={**answer,'game':receipt_game}
            confirm_operation(operation,receipt_answer,selected)
            from .extra_choices import confirm_numeric,confirm_literal
            delta=(confirm_literal if operation['family']=='QUOTED_LITERAL_EXTRA' else confirm_numeric)(domain,selected,receipt_answer)
            if delta<0:
                self.extra_cost-=delta;self.numeric_extra_played=True
                answer['_funded_extra_spin']={'target_phase':game['nextMode'],'price':domain['quoted_price'],'regular_left':game['freespinsLeft'],
                    'flag_contract':domain.get('flag_contract','BOOLEAN'),'remaining_counter_contract':domain.get('remaining_counter_contract')}
        if delta is None and Decimal(str(game.get('win')))<0:
            from .contracts import selection_adjustment
            delta=selection_adjustment(operation,request,answer,previous,self.win)
        if game.get('wasExtraSpin',False) is not False and not ((_extra_response(game) and self.extra_played) or self.numeric_extra_played):
            raise Unlearned('Nolimit City: extra spin sin contrato aprendido')
        self.steps+=1;self.win+=_money(game.get('win')) if delta is None else delta
        self.previous=dict(game)
        if self.win!=_money(game.get('accumulatedRoundWin')):raise ValueError('Nolimit City: premio acumulado incoherente')
        from .state import settled_state
        self.closed=settled_state(answer);self.had_feature|=game.get('nextMode')!='NORMAL'
        observation=answer.get('feature_observation') or {}
        if (not self.closed and self.win>0 and observation.get('kind')=='UNRESOLVED_PHASE'
                and answer.get('balance') is not None):
            # Some clients retain the feature label after its prize is paid.
            # Only a declared/no-choice menu, normal counters and an actual
            # wallet credit can establish that this is an annotation.
            candidate={**answer,'features':{**answer['features'],'active':'','available':[]},
                'feature_observation':{'kind':'PAID_SETTLEMENT_ANNOTATION',
                    'active':answer['features'].get('active'),'source':'normal_state_and_reconciled_wallet_credit'}}
            if (settled_state(candidate)
                    and _money(answer['balance'])==self.before-self.cost+self.win):
                answer=candidate;self.closed=True
        if not self.closed and answer.get('balance') is not None:
            from .state import settled_catalog_subset
            completed_phase=None
            if (isinstance(operation,dict) and operation.get('schema')=='nolimit-city/operation-contract/v1'
                    and previous.get('nextMode')==game.get('mode')
                    and (operation.get('acknowledgment') or {}).get('phase')==game.get('mode')):
                from .contracts import observed_request_matches,confirm_operation
                matches,selected=observed_request_matches(operation,request or {})
                if matches:
                    confirm_operation(operation,raw_answer,selected)
                    completed_phase=game['mode']
            candidate=settled_catalog_subset(answer,self.mode,completed_phase=completed_phase)
            if candidate is not None and _money(answer['balance'])==self.before-self.cost+self.win:
                answer=candidate;self.closed=True
        if (not self.closed and self.win>0 and observation.get('kind')=='UNRESOLVED_MENU'
                and answer.get('balance') is not None
                and _money(answer['balance'])==self.before-self.cost+self.win):
            # A coherent credit is not a wallet error. Unknown menu labels still
            # block certification; this projection only classifies the blocker.
            terminal_view={**answer,'features':{'active':'','available':[]},'feature_observation':{'kind':'NONE'}}
            if settled_state(terminal_view):
                raise Unlearned('Nolimit City: crédito reconciliado con catálogo terminal sin resolver')
        expected=self.before-self.cost+(self.win if self.closed else Decimal(0))
        if answer.get('balance') is not None:
            self.after=_money(answer['balance'])
            if self.after!=expected:raise ValueError('Nolimit City: saldo no explica coste y liquidación')
            balances=answer.get('balances')
            if isinstance(balances,dict) and 'TOTAL_BALANCE' in balances and _money(balances['TOTAL_BALANCE'])!=self.after:
                raise ValueError('Nolimit City: saldos del servidor contradictorios')
        elif self.steps==1 or self.closed:raise ValueError('Nolimit City: falta saldo al apostar o liquidar')
        if self.steps==1:
            from .operation_fields import root_ack
            debit_confirmed=(isinstance(request,dict) and self.cost>self.stake
                and answer.get('balance') is not None and self.after==expected)
            root_ack(game,self.mode,request,debit_confirmed=debit_confirmed)
            self.root_ack_basis=('DECLARED_PURCHASE_AND_DEBIT' if self.mode['kind']=='PURCHASE'
                and 'wasFeatureBuy' not in game and game.get('featureBet') is True
                else 'DECLARED_PRICE_AND_DEBIT' if self.mode['kind']=='FEATURE_SPIN'
                and game.get('wasBoostedBet') is None and game.get('featureBet') is not True
                else 'SERVER_FLAG_OR_OPERATION_ACK')
        if self.numeric_extra_played:answer['_verified_numeric_extra_context']=True
        self.last_answer=answer
        return self.closed
    def proof(self):return {'schema':MONETARY,'before':str(self.before),'cost':str(self.cost),'win':str(self.win),
                           'after':str(self.after),'steps':self.steps,'closed':self.closed,'had_feature':self.had_feature,'extra_spin_cost':str(self.extra_cost),'root_ack_basis':self.root_ack_basis}

def continuation(answer,*,declared_options=(),declared_categories=(),declared_purchase_options=(),declared_catalog=None,declared_game_modes=(),raw_answer=None):
    raw_game=((raw_answer if raw_answer is not None else answer).get('game') or {})
    explicit_no_extra=raw_game.get('wasExtraSpin') is False or raw_game.get('isExtraSpin') is False
    answer=normalized_response(answer,declared_options,declared_categories,declared_purchase_options,declared_catalog=declared_catalog,declared_game_modes=declared_game_modes)
    available=(answer.get('features') or {}).get('available')
    if available!=[]:raise Unlearned('Nolimit City: elección sin primitiva aprendida: '+json.dumps(available,ensure_ascii=True))
    game=answer.get('game') or {}
    left=game.get('freespinsLeft',answer.get('remainingFreeSpins'))
    second=game.get('secondStageFsLeft')
    stage_transition=(type(left) is int and left==0 and type(second) is int and second>0
        and game.get('firstStage') is True and game.get('secondStage') is False
        and all(key in game for key in ('thisSpinWinning','totalSpinWinnings','enhancedBet','featureName')))
    if _pending_auto_phase(answer,game,explicit_no_extra=explicit_no_extra):return {'type':'zeroBet','bet':'0.00'}
    if (_batch_response(game) and game.get('nextMode') in declared_purchase_options
            and type(left) is int and left>0):return {'type':'zeroBet','bet':'0.00'}
    if (_extra_response(game) and game.get('nextMode') in ('FREESPIN_TRIGGER','COIN_SPIN')
            and game.get('isExtraSpin') is False and type(left) is int and left==0
            and game.get('extraSpinCost',0)==0):return {'type':'zeroBet','bet':'0.00'}
    if (_row_response(game) and game.get('nextMode')=='FREESPIN_PICK' and game['wasFeatureBuy'] is True
            and type(game.get('playerSelection')) is int and game['playerSelection']>0
            and game['featureBuyRows']==game['playedRowsInFS'] and left>0):return {'type':'zeroBet','bet':'0.00'}
    extra_cost=game.get('extraSpinCost',0)
    try:free_operation=_money(extra_cost)==0 and game.get('wasExtraSpin',False) is False
    except ValueError:free_operation=False
    if free_operation and game.get('nextMode')=='RESPIN' and type(game.get('respinsLeft')) is int and game['respinsLeft']>0:
        return {'type':'zeroBet','bet':'0.00'}
    if free_operation and game.get('nextMode')=='FREESPIN_MINIGAME' and type(left) is int and left>0:
        return {'type':'zeroBet','bet':'0.00'}
    if (game.get('nextMode') not in {'FREESPIN','FREESPIN_BETTER','FREESPIN_SUPER','SUPER_FREESPIN'}
            or (not stage_transition and (type(left) is not int or left<=0))):
        raise Unlearned('Nolimit City: continuación desconocida: '+str(game.get('nextMode')))
    return {'type':'zeroBet','bet':'0.00'}
