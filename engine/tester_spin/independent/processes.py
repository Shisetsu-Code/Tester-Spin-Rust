"""OS-enforced process trees, including detached browser descendants."""
from __future__ import annotations
import os,subprocess,sys,time,uuid
from pathlib import Path

class UnsafeProcessTree(RuntimeError):
    preserve_network=True

class ProcessTree:
    def __init__(self):
        self.platform=sys.platform;self.bound=False;self.closed=False
        if self.platform=='win32':self._windows()
        elif self.platform=='linux':
            if not Path('/sys/fs/cgroup/cgroup.controllers').is_file():raise RuntimeError('El ejecutor Linux requiere cgroup v2')
            self.path=Path('/sys/fs/cgroup')/('tester-spin-'+uuid.uuid4().hex)
            self._linux(['mkdir','--',str(self.path)])
        else:raise RuntimeError('El ejecutor de procesos admite Windows y Linux')
    def _linux(self,args,*,input=None):
        prefix=[] if os.geteuid()==0 else ['sudo','-n']
        try:answer=subprocess.run(prefix+args,input=input,capture_output=True,text=True,timeout=10)
        except (OSError,subprocess.TimeoutExpired):raise RuntimeError('No se pudo controlar el cgroup del ejecutor') from None
        if answer.returncode:raise RuntimeError('Linux requiere permisos sudo para controlar los procesos de cada juego')
        return answer.stdout
    def _windows(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c=c;self.api=c.WinDLL('kernel32',use_last_error=True)
        class Basic(c.Structure):
            _fields_=[('ProcessTime',c.c_longlong),('JobTime',c.c_longlong),('Flags',w.DWORD),('MinWorkingSet',c.c_size_t),
                ('MaxWorkingSet',c.c_size_t),('ActiveLimit',w.DWORD),('Affinity',c.c_size_t),('Priority',w.DWORD),('Scheduling',w.DWORD)]
        class IO(c.Structure):_fields_=[(k,c.c_ulonglong) for k in ['ReadOps','WriteOps','OtherOps','ReadBytes','WriteBytes','OtherBytes']]
        class Extended(c.Structure):
            _fields_=[('Basic',Basic),('IO',IO),('ProcessMemory',c.c_size_t),('JobMemory',c.c_size_t),('PeakProcessMemory',c.c_size_t),('PeakJobMemory',c.c_size_t)]
        class Accounting(c.Structure):
            _fields_=[(k,c.c_longlong) for k in ['User','Kernel','PeriodUser','PeriodKernel']]+[(k,w.DWORD) for k in ['Faults','Total','Active','Terminated']]
        self.Accounting=Accounting
        prototypes={
            'CreateJobObjectW':([w.LPVOID,w.LPCWSTR],w.HANDLE),
            'SetInformationJobObject':([w.HANDLE,c.c_int,w.LPVOID,w.DWORD],w.BOOL),
            'QueryInformationJobObject':([w.HANDLE,c.c_int,w.LPVOID,w.DWORD,w.LPVOID],w.BOOL),
            'AssignProcessToJobObject':([w.HANDLE,w.HANDLE],w.BOOL),
            'OpenProcess':([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
            'TerminateJobObject':([w.HANDLE,w.UINT],w.BOOL),
            'CloseHandle':([w.HANDLE],w.BOOL)}
        for name,(args,result) in prototypes.items():
            fn=getattr(self.api,name);fn.argtypes=args;fn.restype=result
        self.handle=self.api.CreateJobObjectW(None,None)
        if not self.handle:raise RuntimeError('No se pudo crear el grupo de procesos del juego')
        limits=Extended();limits.Basic.Flags=0x2000 # KILL_ON_JOB_CLOSE; no breakaway flags.
        if not self.api.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)):
            self.api.CloseHandle(self.handle);raise RuntimeError('No se pudo asegurar el cierre de los procesos del juego')
    def bind(self,pid):
        if self.platform=='win32':
            handle=self.api.OpenProcess(0x0101,False,pid) # SET_QUOTA | TERMINATE
            if not handle:raise RuntimeError('No se pudo reservar el proceso del juego')
            try:
                if not self.api.AssignProcessToJobObject(self.handle,handle):raise RuntimeError('No se pudo aislar el árbol de procesos del juego')
            finally:self.api.CloseHandle(handle)
        else:self._linux(['tee',str(self.path/'cgroup.procs')],input=str(pid)+'\n')
        self.bound=True
    def active_count(self):
        if self.platform=='win32':
            info=self.Accounting()
            if not self.api.QueryInformationJobObject(self.handle,1,self.c.byref(info),self.c.sizeof(info),None):
                raise UnsafeProcessTree('No se pudo comprobar el cierre del árbol de procesos; no se cambia la conexión')
            return int(info.Active)
        try:events=self._linux(['cat',str(self.path/'cgroup.events')])
        except RuntimeError:raise UnsafeProcessTree('No se pudo comprobar el cierre del cgroup; no se cambia la conexión') from None
        if 'populated 0' in events:return 0
        return max(1,len(self._linux(['cat',str(self.path/'cgroup.procs')]).split()))
    def stop_and_wait(self,timeout=10):
        try:
            if self.active_count():
                if self.platform=='win32':
                    if not self.api.TerminateJobObject(self.handle,1):raise UnsafeProcessTree('No se pudo cerrar el árbol de procesos del juego')
                else:self._linux(['tee',str(self.path/'cgroup.kill')],input='1\n')
            deadline=time.monotonic()+timeout
            while self.active_count():
                if time.monotonic()>=deadline:raise UnsafeProcessTree('Quedan procesos vivos; se conserva el túnel y no se continúa')
                time.sleep(.05)
        except UnsafeProcessTree:raise
        except Exception:raise UnsafeProcessTree('No se pudo cerrar el árbol de procesos; se conserva el túnel') from None
    def close(self):
        if self.closed:return
        self.stop_and_wait()
        if self.platform=='win32':self.api.CloseHandle(self.handle)
        else:self._linux(['rmdir','--',str(self.path)])
        self.closed=True
