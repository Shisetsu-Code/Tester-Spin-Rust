"""Demo pacing and server cooldown shared across local executor processes."""
import json
import os
import uuid
from pathlib import Path
from contextlib import contextmanager
import math
import threading
import time

@contextmanager
def _file_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if os.name=='nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
            try:
                # Initialize only after acquiring the byte lock: two processes can see an empty file.
                if handle.seek(0,os.SEEK_END)==0:
                    handle.write(b'0');handle.flush()
                handle.seek(0)
                yield
            finally:
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

class RequestGate:
    def __init__(self, *, clock=time.monotonic, interval_s=4.0, wall_clock=time.time, cooldown_path=None):
        self.clock=clock;self.wall_clock=wall_clock
        self.cooldown_path=Path(cooldown_path) if cooldown_path is not None else None
        self.interval_s=float(interval_s)
        if not math.isfinite(self.interval_s) or self.interval_s<0:raise ValueError('Invalid request interval')
        self.lock=threading.Lock();self.next_start=0.0;self.cooldown_until=0.0

    @contextmanager
    def _shared_lock(self):
        if self.cooldown_path is None:
            yield
        else:
            with _file_lock(self.cooldown_path.with_suffix('.lock')):yield

    def _read_state(self):
        state={}
        if self.cooldown_path is None:return state
        try:
            value=json.loads(self.cooldown_path.read_text(encoding='utf-8'))
            for key in ('retry_at','next_start_at'):
                raw=value.get(key)
                if not isinstance(raw,bool) and isinstance(raw,(int,float)) and math.isfinite(raw) and raw>=0:state[key]=float(raw)
        except (OSError,ValueError,TypeError,AttributeError):pass
        return state

    def remaining_cooldown_s(self):
        with self.lock:
            return max(0.0,self.cooldown_until-self.clock(),self.persisted_retry_at()-self.wall_clock())

    def persisted_retry_at(self):
        return self._read_state().get('retry_at',0.0)

    def _write_state(self,state):
        if self.cooldown_path is None:return
        temporary=self.cooldown_path.with_name(self.cooldown_path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_text(json.dumps(state),encoding='utf-8')
            os.replace(temporary,self.cooldown_path)
        finally:temporary.unlink(missing_ok=True)

    def cooldown(self,retry_after):
        try:
            delay=float(retry_after)
            if not math.isfinite(delay) or delay<0:raise ValueError()
        except (ValueError,TypeError):delay=60.0
        with self.lock:
            self.cooldown_until=max(self.cooldown_until,self.clock()+delay)
            self.next_start=max(self.next_start,self.cooldown_until)
            with self._shared_lock():
                state=self._read_state()
                state['retry_at']=max(state.get('retry_at',0.0),self.wall_clock()+delay)
                self._write_state(state)

    def acquire(self,stop_event,*,max_wait_s=None):
        while True:
            if stop_event.is_set():raise InterruptedError('Yggdrasil: execution stopped')
            with self.lock:
                with self._shared_lock():
                    now=self.clock();wall=self.wall_clock();state=self._read_state()
                    remote_delay=max(self.cooldown_until-now,state.get('retry_at',0.0)-wall)
                    delay=max(self.next_start-now,remote_delay,state.get('next_start_at',0.0)-wall)
                    if delay<=0:
                        self.next_start=now+self.interval_s
                        state['next_start_at']=wall+self.interval_s
                        self._write_state(state)
                        return
            if max_wait_s is not None and delay>max_wait_s:
                label='Server 429 cooldown' if remote_delay>max_wait_s else 'Provider pacing'
                raise TimeoutError(label+' exceeds the configured timeout')
            if stop_event.wait(min(delay,0.5)):raise InterruptedError('Yggdrasil: execution stopped')

REQUEST_GATE=RequestGate()
_GATES={}
_GATES_LOCK=threading.Lock()
def gate_for(provider_root):
    path=Path(provider_root).resolve()/'server-cooldown.json'
    with _GATES_LOCK:
        if str(path) not in _GATES:_GATES[str(path)]=RequestGate(cooldown_path=path)
        return _GATES[str(path)]
