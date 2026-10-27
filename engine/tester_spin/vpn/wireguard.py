"""Owned WireGuard tunnel lifetime. Never stops a pre-existing user tunnel."""
from __future__ import annotations
import ipaddress,os,re,shutil,subprocess,sys,tempfile,time,uuid
from pathlib import Path
from .lock import NetworkLock

class NetworkContextError(RuntimeError):pass

def validate_config(path):
    path=Path(path).resolve()
    if path.suffix.casefold()!='.conf' or not path.is_file():raise NetworkContextError('WireGuard: falta un archivo .conf exportado')
    if path.stat().st_size>100_000:raise NetworkContextError('WireGuard: configuración demasiado grande')
    try:text=path.read_text(encoding='utf-8-sig')
    except (OSError,UnicodeError):raise NetworkContextError('WireGuard: no se pudo leer la configuración') from None
    if re.search(r'^\s*(PreUp|PostUp|PreDown|PostDown)\s*=',text,re.M|re.I):
        raise NetworkContextError('WireGuard: los perfiles del ejecutor no admiten hooks personalizados')
    if not re.search(r'^\s*PrivateKey\s*=\s*\S+',text,re.M) or not re.search(r'^\s*PublicKey\s*=\s*\S+',text,re.M):
        raise NetworkContextError('WireGuard: faltan los datos de una configuración de cliente')
    if len(re.findall(r'^\s*\[Peer\]\s*$',text,re.M))!=1:raise NetworkContextError('WireGuard: se requiere un peer de salida por perfil')
    tables=re.findall(r'^\s*Table\s*=([^\r\n#]+)',text,re.M|re.I)
    if any(v.strip().lower()!='auto' for v in tables):raise NetworkContextError('WireGuard: Table debe usar las rutas automáticas')
    if len(re.findall(r'^\s*AllowedIPs\s*=',text,re.M))!=1:raise NetworkContextError('WireGuard: se requiere una sola declaración de rutas')
    allowed=set()
    for value in re.findall(r'^\s*AllowedIPs\s*=([^\r\n#]+)',text,re.M):
        try:allowed.update(str(ipaddress.ip_network(v.strip(),strict=False)) for v in value.split(','))
        except ValueError:raise NetworkContextError('WireGuard: rutas inválidas') from None
    if not {'0.0.0.0/0','::/0'}<=allowed:
        raise NetworkContextError('WireGuard: el perfil debe cubrir IPv4 e IPv6 completos para verificar la salida')
    return text

def public_ip():
    from curl_cffi import requests
    with requests.Session(impersonate='chrome',trust_env=False) as http:
        response=http.get('https://api.ipify.org?format=json',timeout=10);response.raise_for_status()
        return str(ipaddress.ip_address(response.json()['ip']))

class WireGuardTunnel:
    def __init__(self,config,*,platform=None,command=None,ip_probe=None,lock_factory=NetworkLock,connect_timeout=30,stop_event=None):
        self.config=Path(config);self.platform=platform or sys.platform
        self.command=command;self.ip_probe=ip_probe or public_ip;self.lock_factory=lock_factory
        self.connect_timeout=connect_timeout;self.stop_event=stop_event
        self.name='tswg'+uuid.uuid4().hex[:8];self.ip=None;self.installed=False;self.lock=None;self.directory=None
    def _program(self,name):
        if self.command:return name
        path=shutil.which(name)
        if not path and self.platform=='win32':
            candidate=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'WireGuard'/(name+'.exe')
            if candidate.is_file():path=str(candidate)
        if not path:raise NetworkContextError('WireGuard: no está instalado '+name)
        return path
    def _checked(self,args):
        if self.command:result=self.command(args)
        else:
            actual=args
            if self.platform!='win32' and os.geteuid()!=0:actual=['sudo','-n',*args]
            try:
                result=subprocess.run(actual,capture_output=True,text=True,timeout=30,
                    **({'creationflags':subprocess.CREATE_NO_WINDOW} if self.platform=='win32' else {}))
            except (OSError,subprocess.TimeoutExpired):raise NetworkContextError('WireGuard: el comando no respondió o no está disponible') from None
        if result.returncode:raise NetworkContextError('WireGuard: comando falló; comprobá instalación y permisos de administrador')
        return result.stdout.strip()
    def _interfaces(self):return self._checked([self.wg,'show','interfaces']).split()
    def __enter__(self):
        text=validate_config(self.config)
        self.wg=self._program('wg');self.control=self._program('wireguard' if self.platform=='win32' else 'wg-quick')
        if self.platform not in {'win32','linux'}:raise NetworkContextError('WireGuard: plataforma no implementada')
        self.lock=self.lock_factory()
        try:self.lock.__enter__()
        except Exception:
            self.lock=None
            raise NetworkContextError('WireGuard: ya existe una ejecución activa o no se pudo reservar la conexión') from None
        try:
            if self._interfaces():raise NetworkContextError('WireGuard: hay otro túnel activo; no se modifica')
            self.directory=Path(tempfile.mkdtemp(prefix='tester-spin-wg-')).resolve()
            self.owned_config=self.directory/(self.name+'.conf')
            self.owned_config.write_text(text,encoding='utf-8');self.owned_config.chmod(0o600)
            self.installed=True
            args=[self.control,'/installtunnelservice',str(self.owned_config)] if self.platform=='win32' else [self.control,'up',str(self.owned_config)]
            self._checked(args)
            deadline=time.monotonic()+self.connect_timeout
            while True:
                if self.stop_event is not None and self.stop_event.is_set():raise NetworkContextError('WireGuard: conexión cancelada')
                try:self.ip=self.verify();return self
                except NetworkContextError:
                    if time.monotonic()>=deadline:raise
                    if self.stop_event is not None:self.stop_event.wait(.25)
                    else:time.sleep(.25)
        except BaseException:
            self.close();raise
    def verify(self):
        if self._interfaces()!=[self.name]:raise NetworkContextError('WireGuard: el túnel solicitado no es la única conexión activa')
        try:ip=str(ipaddress.ip_address(self.ip_probe()))
        except Exception:raise NetworkContextError('WireGuard: no se pudo verificar la IP de salida') from None
        raw=self._checked([self.wg,'show',self.name,'latest-handshakes'])
        try:timestamps=[int(line.rsplit(None,1)[1]) for line in raw.splitlines()]
        except (ValueError,IndexError):raise NetworkContextError('WireGuard: estado de conexión no reconocido') from None
        if len(timestamps)!=1 or timestamps[0]<=0 or not 0<=time.time()-timestamps[0]<=180:
            raise NetworkContextError('WireGuard: handshake no confirmado')
        if self.ip is not None and ip!=self.ip:raise NetworkContextError('WireGuard: la IP cambió durante el lote')
        return ip
    def close(self):
        try:
            if self.installed:
                args=[self.control,'/uninstalltunnelservice',self.name] if self.platform=='win32' else [self.control,'down',str(self.owned_config)]
                self._checked(args);self.installed=False
            if self.directory is not None:
                # Only the exact private copy created by this object is removed.
                if self.owned_config.parent.resolve()!=self.directory:raise NetworkContextError('WireGuard: ruta de limpieza inválida')
                self.owned_config.unlink(missing_ok=True);self.directory.rmdir();self.directory=None
        finally:
            if self.lock is not None:self.lock.__exit__(None,None,None);self.lock=None
    def __exit__(self,kind,exc,tb):
        if getattr(exc,'preserve_network',False):
            # A live process tree must never lose its current connection.
            # Leave the owned tunnel/config installed; the next run sees it
            # as an existing tunnel and refuses to modify it.
            if self.lock is not None:self.lock.__exit__(kind,exc,tb);self.lock=None
            return False
        self.close()
