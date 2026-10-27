"""Fresh GPAS HTTP bootstrap and direct Socket.IO v1 demo execution."""
import hashlib
import json
import re
import time
import uuid
from urllib.parse import urljoin, urlsplit
import requests
import websocket
from tester_spin.direct_transport import CorrelatedSocket
from .runtime import DemoSession as BrowserDemoSession
from .client_sources import script_dependencies

ROOT='https://gpas-games.playtechone.com/'

class DemoSession(BrowserDemoSession):
    transport_kind='direct-websocket'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.http=requests.Session();self.direct=None;self.entries=[];self.initialized=False;self.adapter_config={}
        self.http.headers.update({'Origin':ROOT.rstrip('/'),'Referer':ROOT+'gpasclient.html'})
    def _get(self,url,*,as_json=True):
        if self.stop.is_set():raise InterruptedError('DETENIDO')
        if urlsplit(url).scheme!='https' or urlsplit(url).hostname not in {'gpas-games.playtechone.com','gpas-stg.playtechone.com','frontend.playtechhorizon.com'}:
            raise ValueError('DIRECT_ENDPOINT_UNSUPPORTED')
        r=self.http.get(url,timeout=self.timeout,allow_redirects=False);r.raise_for_status()
        if r.is_redirect:raise ValueError('DIRECT_REDIRECT_UNSUPPORTED')
        if len(r.content)>8*1024*1024:raise ValueError('DIRECT_RESOURCE_LIMIT')
        self.entries.append({'startedDateTime':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'time':0,
            'request':{'method':'GET','url':url,'httpVersion':'HTTP/1.1','headers':[],'queryString':[],'cookies':[],'headersSize':-1,'bodySize':0},
            'response':{'status':r.status_code,'statusText':r.reason,'httpVersion':'HTTP/1.1','headers':[],'cookies':[],
                'content':{'size':len(r.content),'mimeType':r.headers.get('Content-Type','text/plain'),'text':r.text},'redirectURL':'','headersSize':-1,'bodySize':len(r.content)},
            'cache':{},'timings':{'send':0,'wait':0,'receive':0}})
        return r.json() if as_json else r.content.decode('utf-8')
    def __enter__(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        try:
            release=self._get(ROOT+'gpasclientconf_live.php')['id']
            if not re.fullmatch(r'[0-9.]+',release):raise ValueError('DIRECT_RELEASE_UNSUPPORTED')
            bundle=self._get(ROOT+release+'/logical_bundle.php')
            game_root=urljoin(ROOT,bundle['games'][self.code])
            manifest_url=urljoin(game_root.rstrip('/')+'/', 'packs/manifest.json')
            self.manifest=self._get(manifest_url)
            if self.manifest.get('gameCode')!=self.code:raise ValueError('GAME_IDENTITY_MISMATCH')
            # GLU6 puts script assets under game/, separately from packs/manifest.json.
            script_base=urljoin(game_root.rstrip('/')+'/', 'game/') if self.manifest.get('env',{}).get('glu6') is True else manifest_url
            pending=[urljoin(script_base,r) for r in self.manifest.get('javascript',[])]
            seen=set()
            while pending:
                url=pending.pop(0)
                if url in seen:continue
                if len(seen)>=16:raise ValueError('CLIENT_SOURCE_GRAPH_LIMIT')
                if not url.startswith(game_root.rstrip('/')+'/'):raise ValueError('CLIENT_SOURCE_OUTSIDE_GAME')
                seen.add(url)
                source=self._get(url,as_json=False)
                self.sources.append(source);self.source_hashes.append(hashlib.sha256(source.encode('utf-8')).hexdigest())
                # Static script loaders only. Never evaluate downloaded JavaScript.
                for resource in script_dependencies(source):
                    pending.append(urljoin(script_base,resource))
            if not self.sources:raise ValueError('CLIENT_SOURCES_MISSING')
            from .adapter_config import projects, config_paths, merge_maps
            declared_projects=projects(self.sources)
            if len(declared_projects)>1:raise ValueError('CLIENT_PROJECT_AMBIGUOUS')
            if declared_projects:
                from concurrent.futures import ThreadPoolExecutor
                project_url=urljoin(script_base,declared_projects[0])
                project=self._get(project_url)
                paths=config_paths(project)
                urls=[urljoin(project_url,path) for path in paths]
                if any(not url.startswith(game_root.rstrip('/')+'/') for url in urls):raise ValueError('CLIENT_SOURCE_OUTSIDE_GAME')
                with ThreadPoolExecutor(max_workers=6) as pool:
                    documents=list(pool.map(self._get,urls))
                self.adapter_config=merge_maps(documents)

            server=self._get(ROOT+release+'/brands/playtechhorizon/1/json/env_config.json')['server']
            if str(server.get('secure')).lower()!='true':raise ValueError('INSECURE_DEMO_ENDPOINT')
            host=server['host']
            if host not in {'gpas-stg.playtechone.com','frontend.playtechhorizon.com'}:raise ValueError('DIRECT_ENDPOINT_UNSUPPORTED')
            handshake=self._get('https://'+host+'/socket.io/1/?t='+str(int(time.time()*1000)),as_json=False).split(':')
            if len(handshake)!=4 or 'websocket' not in handshake[3].split(',') or not re.fullmatch(r'[A-Za-z0-9_-]+',handshake[0]):raise ValueError('SOCKET_HANDSHAKE_UNSUPPORTED')
            url='wss://'+host+'/socket.io/1/websocket/'+handshake[0]
            wire=websocket.create_connection(url,timeout=self.timeout,origin=ROOT.rstrip('/'))
            self.bindings['1']=self.code;self.socket_urls['1']=url
            self.direct=CorrelatedSocket(wire,self.stop,self.timeout,observe=lambda direction,payload:self._packet('1',direction,payload),heartbeat_response={'2::':'2::'},disconnect_frames=('0::',))
            self.direct.wait(lambda p:p=='1::')
            identity=str(uuid.uuid4())
            self._request({'_type':'InitGameSession','casino':'playtechhorizon','clientType':'casino','clientPlatform':'web','language':'EN','gameCode':self.code,
                'username':identity,'token':identity,'resume':False,'apiFeatures':['freespinTotalBalance','freespin2'],'real':0},'InitGameSessionResponse')
            self.initialized=True
            self._request({'_type':'GetClientState'},'GetClientStateResponse')
            self._request({'_type':'com.pt.gpas.config.GetGameConfigurationRequest','scoped':True,'disablePersonalizedBets':True},'GetGameConfigurationResponse')
            self.wait(lambda:self.balance is not None and self.config is not None,'BOOTSTRAP_INCOMPLETE')
            self.demo_verified=True
            return self
        except BaseException:
            self.__exit__(None,None,None);raise
    def _request(self,data,response_type=None):
        correlation='tester-'+uuid.uuid4().hex
        def accept(payload):
            if self.errors:return True
            if not isinstance(payload,str) or not payload.startswith('3:::'):return False
            try:packet=json.loads(payload[4:])
            except ValueError:return False
            return packet.get('correlationId')==correlation and (response_type is None or packet.get('data',{}).get('_type','').endswith(response_type))
        payload=self.direct.exchange('3:::'+json.dumps({'data':data,'correlationId':correlation}),accept)
        if self.errors:raise ValueError(self.errors[-1])
        return json.loads(payload[4:])['data']
    def wait(self,predicate,reason):
        if self.errors:raise ValueError(self.errors[-1])
        if predicate():return
        try:self.direct.wait(lambda p:bool(predicate()) or bool(self.errors))
        except TimeoutError as exc:raise TimeoutError(reason) from exc
        if self.errors:raise ValueError(self.errors[-1])
    def exchange(self,command,contract):
        if not self.demo_verified:raise ValueError('DEMO_MODE_NOT_CONFIRMED')
        # No retries or browser fallback after dispatch: the wager may have committed.
        before=len(self.replies)
        self._request(command)
        if len(self.replies)!=before+1:raise ValueError('COMMAND_RESPONSE_MISSING')
        return self.replies[-1][1]
    def __exit__(self,*args):
        try:
            if self.direct:self.direct.__exit__(*args)
        finally:self.http.close()
        self.direct=None
        self.directory.mkdir(parents=True,exist_ok=True)
        data={'log':{'version':'1.2','creator':{'name':'Tester-Spin direct','version':'1'},'entries':self.entries,'_warpWebSockets':self.frames,
            '_testerSpin':{'provider':'playtech','gameCode':self.code,'fresh_demo':self.demo_verified,'transport':'direct-websocket'}}}
        (self.directory/'session.har').write_text(json.dumps(data),encoding='utf-8')
