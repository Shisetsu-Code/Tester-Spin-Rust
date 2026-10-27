"""Open games through HardFire's local MCP without replacing existing tabs."""
import json,os,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
import requests

class HardFireError(RuntimeError):pass

class HardFireClient:
    def __init__(self,endpoint=None,session=None):
        self.endpoint=endpoint or os.environ.get('HARDFIRE_MCP_URL','http://127.0.0.1:8765/mcp')
        try:
            parsed=urlsplit(self.endpoint);port=parsed.port
            valid=(parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost','::1')
                and parsed.path=='/mcp' and not parsed.query and not parsed.fragment and parsed.username is None)
            if not valid:raise ValueError()
        except ValueError:raise HardFireError('La conexión de HardFire debe ser un endpoint MCP local.') from None
        self.port=port or 80
        self.health=urlunsplit((parsed.scheme,parsed.netloc,'/health','',''))
        self.session=session or requests.Session();self.session.trust_env=False;self.counter=0

    def ready(self):
        try:
            response=self.session.get(self.health,timeout=1);response.raise_for_status();value=response.json()
        except (requests.RequestException,ValueError):return False
        if not isinstance(value,dict) or value.get('service')!='hardfire-local-mcp':
            raise HardFireError('El puerto configurado no corresponde a HardFire.')
        return value.get('ok') is True

    def ensure_running(self):
        if self.ready():return
        if os.name=='nt' and os.environ.get('USERNAME','').casefold().startswith('codexsandbox'):
            if self.port!=8765:raise HardFireError('Abrí HardFire con tu usuario de Windows.')
            subprocess.run(['schtasks.exe','/Run','/TN','HardFire Local User'],check=True,
                capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            configured=os.environ.get('HARDFIRE_APP_PATH','').strip()
            candidates=[Path(configured)] if configured else [
                Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Programs/HardFire/HardFire.exe',Path('C:/HardFire')]
            command=None;cwd=None
            for candidate in candidates:
                if candidate.is_file() and candidate.suffix.casefold()=='.exe':
                    command=[str(candidate),'--hardfire-visible'];cwd=candidate.parent;break
                manifest=candidate/'package.json';electron=candidate/'node_modules/electron'
                try:
                    if json.loads(manifest.read_text(encoding='utf-8')).get('name')!='hardfire':continue
                    executable=electron/'dist'/((electron/'path.txt').read_text(encoding='utf-8').strip())
                    if executable.is_file():command=[str(executable),str(candidate),'--hardfire-visible'];cwd=candidate;break
                except (OSError,ValueError,AttributeError):continue
            if command is None:raise HardFireError('No encontré HardFire. Abrilo o configurá HARDFIRE_APP_PATH con su instalación.')
            env=dict(os.environ,HARDFIRE_HEADLESS='0',HARDFIRE_MCP_PORT=str(self.port));env.pop('ELECTRON_RUN_AS_NODE',None)
            subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if self.ready():return
            time.sleep(.15)
        raise HardFireError('HardFire no terminó de iniciar en 30 segundos.')

    def _rpc(self,name,arguments,*,raw=False,timeout=30):
        self.counter+=1
        response=self.session.post(self.endpoint,headers={'Accept':'application/json, text/event-stream'},
            json={'jsonrpc':'2.0','id':self.counter,'method':'tools/call','params':{'name':name,'arguments':arguments}},timeout=timeout)
        response.raise_for_status();message=response.json()
        result=message.get('result') if isinstance(message,dict) else None
        if not isinstance(result,dict) or message.get('id')!=self.counter or message.get('error') or result.get('isError'):
            raise HardFireError('HardFire no pudo completar la acción. Revisá la conexión y el estado de la pestaña.')
        if raw:return result
        for block in result.get('content',[]):
            if block.get('type')=='text':
                try:return json.loads(block['text'])
                except (ValueError,KeyError):continue
        return result

    def open_game(self,url):
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username is not None:
            raise HardFireError('El juego debe tener un enlace HTTP o HTTPS válido.')
        self.ensure_running()
        self._rpc('hardfire_browser',{'mode':'visible'})
        return self._rpc('hardfire_tab_new',{'url':url,'activate':True})
