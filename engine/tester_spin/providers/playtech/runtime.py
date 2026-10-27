"""Fresh, isolated GPAS demo sessions. No HAR replay or UI exploration."""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from .primitives import COMMAND, decode_game_data


class DemoSession:
    def __init__(self, code, directory, timeout_s, stop_event):
        self.code=code;self.directory=Path(directory);self.timeout=max(5,float(timeout_s));self.stop=stop_event
        self.demo_verified=False;self.config=None;self.manifest=None;self.sources=[];self.source_hashes=[]
        self.balance=None;self.replies=[];self.errors=[];self.frames=[];self.bindings={};self.socket_urls={};self.first=True
        self.pw=None;self.browser=None;self.context=None;self.page=None;self.frame_bytes=0

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.directory.mkdir(parents=True,exist_ok=True)
        self.pw=sync_playwright().start()
        try:
            self.browser=self.pw.chromium.launch(headless=True,timeout=int(self.timeout*1000))
            self.context=self.browser.new_context(record_har_path=str(self.directory/'session.har'),record_har_content='embed',
                record_har_url_filter=re.compile(r'(manifest\.json|\.js(?:\?|$)|gpasclient\.html|casinoclient\.html|socket\.io)', re.I))
            self.page=self.context.new_page()
            self.page.add_init_script("""(()=>{const send=WebSocket.prototype.send;WebSocket.prototype.send=function(t){
              if(typeof t==='string'&&t.startsWith('3:::')){try{const m=JSON.parse(t.slice(4));
              if(m.data?._type==='com.pt.casino.platform.game.GameCommand'){window.__testerSocket=this;window.__testerEnvelope=m;}}catch(e){}}
              return send.call(this,t);};})();""")
            self.page.add_init_script("""(()=>{const timer=setInterval(()=>{
                if(typeof GLU==='undefined'||!GLU.game||typeof GLU.game.loadingProgress!=='function')return;
                const original=GLU.game.loadingProgress;
                GLU.game.loadingProgress=function(...args){const result=original.apply(this,args);
                    if(args.some(v=>typeof v==='number'&&v===100))window.__testerAssetsReady=true;
                    return result;};clearInterval(timer);
            },1);})();""")
            self.page.on('response',self._resource)
            self.page.on('websocket',self._socket)
            launch='https://cachedownload.playtechone.com/ngmdesktop/casinoclient.html?'+urlencode({'game':self.code,'preferedmode':'offline','real':'0'})
            self.page.goto(launch,wait_until='domcontentloaded',timeout=int(self.timeout*1000))
            self.wait(lambda:self.config is not None and self.manifest is not None and self.sources and self.balance is not None,'BOOTSTRAP_INCOMPLETE')
            self.wait(lambda:self.page.evaluate("typeof GLU!=='undefined' && typeof GLU.game?.isReal==='function'"),'GLU_NOT_READY')
            self.wait(lambda:self.page.evaluate('window.__testerAssetsReady===true'),'CLIENT_ASSETS_NOT_READY')
            if self.page.evaluate('GLU.game.isReal()') is not False:raise ValueError('DEMO_MODE_NOT_CONFIRMED')
            self.demo_verified=True
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def _resource(self,response):
        url=response.url
        if urlsplit(url).hostname!='gpas-games.playtechone.com' or '/'+self.code+'/' not in url:return
        try:
            if '/manifest.json' in url:
                manifest=response.json()
                if isinstance(manifest,dict) and manifest.get('gameCode')==self.code:self.manifest=manifest
            elif re.search(r'\.js(?:\?|$)',url):
                body=response.body()
                if len(body)>8*1024*1024:return
                source=body.decode('utf-8',errors='replace')
                if 'GLU.game.' in source and ('40021' in source or '48775' in source):
                    digest=hashlib.sha256(body).hexdigest()
                    if digest not in self.source_hashes:self.sources.append(source);self.source_hashes.append(digest)
        except Exception:
            return  # Missing source/configuration is reported by bootstrap timeout.

    def _socket(self,socket):
        if urlsplit(socket.url).hostname not in {'gpas-stg.playtechone.com','frontend.playtechhorizon.com'}:return
        key=str(len(self.bindings)+1);self.bindings[key]=None;self.socket_urls[key]=socket.url
        socket.on('framesent',lambda payload:self._packet(key,'sent',payload))
        socket.on('framereceived',lambda payload:self._packet(key,'received',payload))

    def _packet(self,key,direction,payload):
        if not isinstance(payload,str):return
        if len(self.frames)<20000 and self.frame_bytes+len(payload)<32*1024*1024:
            self.frames.append({'url':self.socket_urls[key],'connectionId':key,'direction':direction,'timestamp':time.time(),'payload':payload,'opcode':1})
            self.frame_bytes+=len(payload)
        else:
            if 'WS_CAPTURE_LIMIT' not in self.errors:self.errors.append('WS_CAPTURE_LIMIT')
        if not payload.startswith('3:::'):return
        try:packet=json.loads(payload[4:]);data=packet.get('data',{})
        except (ValueError,AttributeError):return
        if not isinstance(data,dict):return
        kind=data.get('_type','')
        if direction=='sent' and kind=='InitGameSession':self.bindings[key]=data.get('gameCode')
        if self.bindings[key]!=self.code or direction!='received':return
        if kind.endswith('GetGameConfigurationResponse'):self.config=data.get('data')
        elif kind.endswith('BalanceNotification'):
            values=[b.get('amount') for b in data.get('balance',[]) if isinstance(b,dict) and b.get('_type','').endswith('MonetaryBalanceData')]
            if len(values)==1 and type(values[0]) is int:self.balance=values[0]
        elif kind==COMMAND:
            try:
                clean={k:v for k,v in data.items() if k in {'_type','gameData','stakeAmount','betCost','winAmount','betType','featureType','gameRoundClosed'}}
                clean['gameData']=decode_game_data(data.get('gameData'))
                self.replies.append((packet.get('correlationId'),clean))
            except ValueError as exc:self.errors.append(str(exc))
        elif 'Error' in kind:self.errors.append(kind+':'+str(data.get('code','unknown')))

    def wait(self,predicate,reason):
        deadline=time.monotonic()+self.timeout
        while time.monotonic()<deadline:
            if self.stop.is_set():raise InterruptedError('DETENIDO')
            if self.errors:raise ValueError(self.errors[-1])
            if predicate():return
            self.page.wait_for_timeout(100)
        raise TimeoutError(reason)

    def exchange(self,command,contract):
        count=len(self.replies)
        if self.first:
            result=self.page.evaluate("""({command,legacy})=>{try{
                const data={...command.gameData};delete data._type;
                if(legacy)GLU.game.bet(command.gameData._type,data);
                else {GLU.game.report.stake(command.betCost);GLU.game.playMoney(command.gameData._type,data,command.featureType);}
                return {ok:true};}catch(e){return {error:String(e)}}}""",{'command':command,'legacy':contract['dialect']=='legacy'})
            if result.get('error'):raise ValueError('CLIENT_API_REJECTED:'+result['error'][:200])
            self.first=False
            self.wait(lambda:len(self.replies)>count,'GAME_COMMAND_TIMEOUT')
            return self.replies[-1][1]
        correlation='tester-'+uuid.uuid4().hex
        self.page.evaluate("""({command,id})=>{if(!window.__testerSocket||window.__testerSocket.readyState!==1)throw Error('DEMO_SOCKET_CLOSED');
            const envelope={...window.__testerEnvelope,correlationId:id,t:Date.now(),data:command};
            window.__testerSocket.send('3:::'+JSON.stringify(envelope));}""",{'command':command,'id':correlation})
        self.wait(lambda:any(c==correlation for c,d in self.replies[count:]),'GAME_COMMAND_TIMEOUT')
        return next(d for c,d in self.replies[count:] if c==correlation)

    def __exit__(self,*args):
        try:
            if self.context:self.context.close()
        finally:
            try:
                if self.browser:self.browser.close()
            finally:
                if self.pw:self.pw.stop()
        har=self.directory/'session.har'
        if har.is_file():
            data=json.loads(har.read_text(encoding='utf-8'))
            data['log']['_warpWebSockets']=self.frames
            data['log']['_testerSpin']={'provider':'playtech','gameCode':self.code,'fresh_demo':self.demo_verified,'capture_limited':bool(self.errors and 'WS_CAPTURE_LIMIT' in self.errors)}
            har.write_text(json.dumps(data),encoding='utf-8')
