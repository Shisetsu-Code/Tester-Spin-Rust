"""Machine-wide lease: changing a host route must not overlap managed runs."""
import os,tempfile,threading
from pathlib import Path

_local=threading.Lock()

class NetworkLock:
    def __enter__(self):
        if not _local.acquire(blocking=False):raise RuntimeError('Ya hay una ejecución WireGuard activa en este equipo')
        self.handle=None
        try:
            if os.name=='nt':
                import ctypes
                from ctypes import wintypes
                self.api=ctypes.WinDLL('kernel32',use_last_error=True)
                self.api.CreateMutexW.argtypes=(wintypes.LPVOID,wintypes.BOOL,wintypes.LPCWSTR);self.api.CreateMutexW.restype=wintypes.HANDLE
                self.api.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
                self.api.ReleaseMutex.argtypes=(wintypes.HANDLE,);self.api.CloseHandle.argtypes=(wintypes.HANDLE,)
                self.handle=self.api.CreateMutexW(None,False,'Global\\TesterSpinWireGuard')
                if not self.handle:raise RuntimeError('No se pudo reservar la conexión WireGuard del equipo')
                if self.api.WaitForSingleObject(self.handle,0) not in (0,0x80):raise RuntimeError('Ya hay una ejecución WireGuard activa en este equipo')
            else:
                import fcntl
                self.handle=open(Path(tempfile.gettempdir())/'tester-spin-wireguard.lock','a+b')
                fcntl.flock(self.handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return self
        except BaseException:
            if self.handle:
                if os.name=='nt':self.api.CloseHandle(self.handle)
                else:self.handle.close()
            _local.release();raise
    def __exit__(self,*args):
        try:
            if os.name=='nt':self.api.ReleaseMutex(self.handle);self.api.CloseHandle(self.handle)
            else:self.handle.close()
        finally:_local.release()
