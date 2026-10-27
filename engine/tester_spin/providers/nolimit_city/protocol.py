from urllib.parse import parse_qs
"""Offline Nolimit City protocol primitives grounded in captured client code.

This decodes supplied captures; it does not replay sessions or certify live OK.
"""
import base64,json,re
from decimal import Decimal,InvalidOperation
from urllib.parse import urlsplit

MAX_BODY=8_000_000

def rc4_hex(key,value):
    if not isinstance(key,str) or not key or not isinstance(value,str) or len(value)>MAX_BODY*2 or len(value)%2 or not re.fullmatch('[0-9a-fA-F]+',value):
        raise ValueError('Nolimit City: clave o trama RC4 inválida')
    try:keybytes=key.encode('latin1');data=bytes.fromhex(value)
    except (ValueError,UnicodeError):raise ValueError('Nolimit City: codificación RC4 desconocida')
    box=list(range(256));j=0
    for i in range(256):
        j=(j+box[i]+keybytes[i%len(keybytes)])%256;box[i],box[j]=box[j],box[i]
    result=bytearray();i=j=0
    for byte in data:
        i=(i+1)%256;j=(j+box[i])%256;box[i],box[j]=box[j],box[i]
        result.append(byte^box[(box[i]+box[j])%256])
    return result.decode('latin1')

def lzw_decode(value,*,max_output=MAX_BODY):
    if not isinstance(value,str) or len(value)>max_output:raise ValueError('Nolimit City: trama demasiado grande o inválida')
    if not value.startswith('lzw:'):return value
    raw=value[4:].encode('utf-16-le',errors='surrogatepass')
    codes=[int.from_bytes(raw[i:i+2],'little') for i in range(0,len(raw),2)]
    if not codes or codes[0]>=256:raise ValueError('Nolimit City: inicio LZW inválido')
    previous=chr(codes[0]);result=[previous];size=1;table={};nextcode=256
    for code in codes[1:]:
        if code<256:word=chr(code)
        elif code in table:word=table[code]
        elif code==nextcode:word=previous+previous[0]
        else:raise ValueError('Nolimit City: referencia LZW inválida')
        size+=len(word)
        if size>max_output:raise ValueError('Nolimit City: expansión LZW excede el límite')
        result.append(word);table[nextcode]=previous+word[0];nextcode+=1;previous=word
    return ''.join(result)

def websocket_url(http_url,key):
    parsed=urlsplit(http_url)
    if (parsed.scheme!='https' or parsed.hostname!='demo.nolimitcity.com'
            or parsed.path!='/EjsGameWeb/gs' or parsed.query or parsed.fragment
            or not isinstance(key,str) or not key):
        raise ValueError('Nolimit City: ruta de conexión no demostrada')
    # Captured GameCommunication.connect transforms the server HTTP URL and
    # appends this session key literally; it is not a static provider credential.
    return re.sub('^http','ws',http_url+'?data='+key).replace('/gs?data=','/ws/game?data=')

def decode_capture(document):
    log=document.get('log') or {};frames=log.get('_warpWebSockets')
    entry_format=False
    if not isinstance(frames,list) or not frames:
        entry_format=True
        frames=[{'url':entry.get('request',{}).get('url',''),'direction':frame.get('direction'),
                 'timestamp':frame.get('timestamp'),'payload':frame.get('payloadData'),
                 'late_attach':entry.get('_webSocketLateAttach',False)}
                for entry in log.get('entries',[]) for frame in entry.get('_webSocketFrames',[])
                if frame.get('opcode')==1]
    if not frames:raise ValueError('Nolimit City: faltan mensajes WebSocket')
    bootstraps={}
    for entry in log.get('entries',[]):
        request=entry.get('request') or {};url=urlsplit(request.get('url',''))
        if request.get('method')!='POST' or url.path!='/EjsFrontWeb/fs' or url.hostname!='demo.nolimitcity.com':continue
        content=(entry.get('response') or {}).get('content') or {};text=content.get('text','')
        if content.get('encoding')=='base64':text=base64.b64decode(text).decode('utf-8')
        try:config=json.loads(text)
        except (ValueError,TypeError):continue
        if isinstance(config,dict) and isinstance(config.get('key'),str) and isinstance(config.get('url'),str):
            target=websocket_url(config['url'],config['key'])
            if target in bootstraps and bootstraps[target]!=config['key']:
                raise ValueError('Nolimit City: varias claves para la misma conexión; captura ambigua')
            bootstraps[target]=config['key']
    decoded=[];connections={}
    for index,frame in enumerate(frames):
        url=frame.get('url','');parsed=urlsplit(url)
        if parsed.scheme!='wss' or parsed.hostname!='demo.nolimitcity.com' or parsed.path!='/EjsGameWeb/ws/game':continue
        if url not in bootstraps and entry_format and frame.get('late_attach'):
            values=parse_qs(parsed.query).get('data',[])
            if len(values)==1 and values[0]:bootstraps[url]=values[0]
        if url not in bootstraps:raise ValueError('Nolimit City: falta la clave de la conexión capturada')
        payload=frame.get('payload');direction=frame.get('direction')
        if frame.get('encoding')=='base64':payload=base64.b64decode(payload).decode('utf-8')
        if direction=='sent':
            text=rc4_hex(bootstraps[url],payload)
            # The historical Tester writer hex-encoded plaintext before RC4.
            # The browser sends JSON directly. Both remain bound to this URL's key.
            if re.fullmatch(r'[0-9a-fA-F]+',text or '') and len(text)%2==0:
                text=bytes.fromhex(text).decode('latin1')
        elif direction=='received':text=lzw_decode(payload)
        else:raise ValueError('Nolimit City: dirección de trama desconocida')
        try:message=json.loads(text)
        except (ValueError,TypeError):raise ValueError('Nolimit City: trama descodificada no es JSON')
        if not isinstance(message,dict):raise ValueError('Nolimit City: sobre de mensaje inválido')
        connection=connections.setdefault(url,len(connections))
        decoded.append({'connection':connection,'index':index,'direction':direction,'timestamp':frame.get('timestamp'),'message':message})
    if not decoded:raise ValueError('Nolimit City: no hay mensajes de juego reconocidos')
    return decoded

def _money(value,*,positive=False):
    if isinstance(value,bool) or value is None:raise ValueError('Nolimit City: importe ausente o inválido')
    try:result=Decimal(str(value))
    except InvalidOperation:raise ValueError('Nolimit City: importe inválido')
    if not result.is_finite() or result<0 or (positive and result==0):raise ValueError('Nolimit City: importe fuera de dominio')
    return result

def _closed(message):
    game=message.get('game') or {};available=(message.get('features') or {}).get('available')
    return game.get('nextMode')=='NORMAL' and type(game.get('freespinsLeft')) is int and game['freespinsLeft']==0 and available==[]

def analyze_messages(rows,*,client_source=None,direct_demo_transport=False):
    connections={}
    for row in rows:connections.setdefault(row.get('connection',0),[]).append(row)
    if len(connections)>1:
        reports=[];incomplete=[]
        for connection,items in connections.items():
            try:reports.append({'connection':connection,**analyze_messages(items,client_source=client_source,direct_demo_transport=direct_demo_transport)})
            except ValueError as exc:incomplete.append({'connection':connection,'reason':str(exc)})
        return {'schema':'nolimit-city/multi-session-har-analysis/v1','sessions':reports,
                'incomplete_sessions':incomplete,'ok_certified':False}
    from .runtime import RoundLedger
    pending={};exchanges=[]
    for row in rows:
        message=row['message'];identifier=message.get('id')
        if not isinstance(identifier,str) or not identifier:raise ValueError('Nolimit City: mensaje sin identidad')
        if row['direction']=='sent':
            if identifier in pending:raise ValueError('Nolimit City: petición duplicada')
            pending[identifier]=message
        else:
            if identifier not in pending:raise ValueError('Nolimit City: respuesta sin petición correspondiente')
            exchanges.append((pending.pop(identifier),message))
    if not exchanges or exchanges[0][0].get('type')!='init':raise ValueError('Nolimit City: inicialización ausente')
    init=exchanges[0][1];table=(init.get('game') or {}).get('featureBuyTimesBetValue');allowed=init.get('allowedFeatureBets')
    if not isinstance(table,list) or not isinstance(allowed,list) or len(set(allowed))!=len(allowed):raise ValueError('Nolimit City: dominio de opciones incompleto')
    quotes={};purchase=[];boosted=[];unknown=[]
    for item in table:
        name=item.get('name')
        if not isinstance(name,str) or name in quotes:raise ValueError('Nolimit City: opción inválida o duplicada')
        price=_money(item.get('price'),positive=True);quotes[name]={'price':price,'type':item.get('type')}
        if name not in allowed:continue
        option={'id':name,'price_multiplier':str(price),'server_type':item.get('type')}
        if item.get('type')=='FREESPIN':purchase.append(option)
        elif item.get('type') in ('BOOSTED_BET','BOOSTED_BET_X_ROWS'):boosted.append(option)
        else:unknown.append(option)
    if any(name not in quotes for name in allowed):raise ValueError('Nolimit City: selector permitido sin precio declarado')
    before=_money(init.get('balance'));initial=before;total_paid=Decimal(0);total_win=Decimal(0)
    active=None;roots=closed=zero=consecutive=0;observed=set();round_summaries=[];previous_response=None
    for request,response in exchanges[1:]:
        content=request.get('content') or {};kind=content.get('type');operation=None
        if request.get('type')!='normal':raise ValueError('Nolimit City: comando exterior sin contrato aprendido')
        if kind in {'normalBet','featureBet'}:
            if active is not None:raise ValueError('Nolimit City: apuesta nueva con ronda pendiente')
            stake=_money(content.get('bet'),positive=True);selector=content.get('featureName')
            if kind=='normalBet':category='normal';price=Decimal(1);mode_kind='SPIN'
            else:
                if selector not in allowed or (content.get('playerInteraction') or {}).get('featureName')!=selector:
                    raise ValueError('Nolimit City: selector no coincide con el dominio anunciado')
                quote=quotes[selector];price=quote['price'];observed.add(selector)
                if quote['type']=='FREESPIN':category='purchase';mode_kind='PURCHASE'
                elif quote['type'] in ('BOOSTED_BET','BOOSTED_BET_X_ROWS'):category='boosted_bet';mode_kind='FEATURE_SPIN'
                else:raise ValueError('Nolimit City: tipo de opción no aprendido')
            from .declarations import declared_options
            declared,_=declared_options(init)
            original=next((item for item in declared if item['kind']==mode_kind
                and (kind=='normalBet' or item.get('selector')==selector)),None)
            if original is None:raise ValueError('Nolimit City: operación fuera de la declaración compartida')
            mode={**original,'stake':str(stake),'price_multiplier':str(price),'selector':selector}
            ledger=RoundLedger(before,mode)
            active={'category':category,'selector':selector,'cost':ledger.cost,'ledger':ledger,'first_request':request['id']}
            roots+=1;total_paid+=ledger.cost
        elif kind in ('zeroBet','gambleBet'):
            if active is None or _money(content.get('bet'))!=0:raise ValueError('Nolimit City: continuación fuera de ronda o con cargo')
            if client_source is not None:
                from .contracts import resolve_operation,observed_request_matches,confirm_operation
                operation=resolve_operation(active['ledger'].last_answer,active['ledger'].mode,
                    raw_answer=previous_response,client_source=client_source,direct_demo_transport=direct_demo_transport)
                matches,selected=observed_request_matches(operation,content)
                if not matches:raise ValueError('Nolimit City: petición capturada fuera del contrato de cliente')
                confirm_operation(operation,response,selected)
            if kind=='zeroBet':zero+=1
        else:raise ValueError('Nolimit City: tipo de apuesta desconocido')
        ledger=active['ledger'];done=ledger.accept(response,request=content,operation=operation,client_source=client_source);before=ledger.after
        previous_response=response
        if done:
            closed+=1;total_win+=ledger.win
            normal=active['category']=='normal' and not ledger.had_feature
            consecutive=consecutive+1 if normal else 0
            round_summaries.append({'category':active['category'],'selector':active['selector'],'cost':str(active['cost']),
                'win':str(ledger.win),'steps':ledger.steps,'first_request':active['first_request'],'last_request':request['id']})
            active=None
    return {'schema':'nolimit-city/har-protocol-analysis/v1','source':'captured_init_and_matched_websocket_messages',
        'request_count':len(exchanges)+len(pending),'paid_rounds':roots,'closed_rounds':closed,'zero_bet_continuations':zero,
        'initial_balance':str(initial),'final_balance':str(before),'total_paid':str(total_paid),'total_win':str(total_win),
        'domains':{'purchase':{'options':purchase,'complete':not unknown},'boosted_bet':{'options':boosted,'complete':not unknown}},
        'unknown_options':unknown,'observed_selectors':sorted(observed),'unobserved_selectors':sorted(set(allowed)-observed),
        'pending_requests':len(pending),'pending_round':active is not None,'consecutive_normal_at_end':consecutive,
        'rounds':round_summaries,'ok_certified':False}
