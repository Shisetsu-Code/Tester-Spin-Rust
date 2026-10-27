"""A fresh process per game, using the original scheduler and finalizers."""
from __future__ import annotations
import contextlib,json,multiprocessing as mp,os,time,uuid
from dataclasses import fields
from pathlib import Path
from tester_spin.models import GameTestResult,SpinAttempt
from .processes import ProcessTree,UnsafeProcessTree

def result_from_payload(payload):
    names={f.name for f in fields(GameTestResult)}
    data={k:v for k,v in payload.items() if k in names}
    attempts={f.name for f in fields(SpinAttempt)}
    data['attempts']=[SpinAttempt(**{k:v for k,v in a.items() if k in attempts}) for a in data.get('attempts',[])]
    return GameTestResult(**data)

def _worker(game,data_root,spins,timeout,stop,result_path,log_path,vpn,gate):
    gate.wait()
    if stop.is_set():return
    if vpn:
        for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):os.environ.pop(key,None)
    with open(log_path,'w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        from tester_spin.providers.registry import create_provider
        from tester_spin.scheduler import run_game_tests
        provider=create_provider(game.provider,Path(data_root))
        def save(result):Path(result_path).write_text(json.dumps(result.to_dict(),ensure_ascii=False),encoding='utf-8')
        block_check=getattr(provider,'test_start_block_reason',None)
        block_reason=block_check(timeout_s=timeout) if block_check is not None else ''
        if block_reason:
            result=GameTestResult(game.provider,game.slug,game.name,game.url,max(1,int(spins)),0,max(1,int(spins)),
                'ERROR',symbol=game.symbol,error=block_reason)
            metadata_check=getattr(provider,'test_start_block_metadata',None)
            metadata=metadata_check() if metadata_check is not None else {}
            if isinstance(metadata,dict):result.structural_map.update(metadata)
            result.structural_map['execution_block']={'source':'provider.test_start_block_reason','reason':block_reason}
            save(result)
            return
        run_game_tests(provider,[game],concurrency=1,spins_per_game=spins,delay_between_starts_s=0,
            timeout_s=timeout,stop_event=stop,progress=lambda _:None,on_result=save)

def execute_game(game,*,data_root,run_root,spins,timeout,wall_timeout,stop_event,vpn=False):
    context=mp.get_context('spawn');identifier=uuid.uuid4().hex
    path=Path(run_root)/(identifier+'.private.result.json');log=Path(run_root)/(identifier+'.private.log')
    gate=context.Event();tree=ProcessTree()
    process=context.Process(target=_worker,args=(game,str(data_root),spins,timeout,stop_event,str(path),str(log),vpn,gate))
    started=False
    try:
        process.start();started=True
        tree.bind(process.pid) # Child cannot launch any provider/browser before this gate.
        gate.set();deadline=time.monotonic()+wall_timeout;reason=None
        while process.is_alive():
            process.join(.2)
            if stop_event.is_set():reason='CANCELADO';break
            if time.monotonic()>=deadline:reason='ERROR';break
        tree.stop_and_wait() # Includes detached browser/driver descendants.
        process.join(5)
        if process.is_alive():raise UnsafeProcessTree('El árbol del juego no cerró; no se cambia de conexión')
        if reason:
            result=GameTestResult(game.provider,game.slug,game.name,game.url,spins,0,spins,reason,symbol=game.symbol,
                error='INDEPENDENT_CANCELLED' if reason=='CANCELADO' else 'RUNNER_WALL_TIMEOUT')
            result.structural_map['execution_abort']={'forced':True,'reason':result.error}
            return result
        if process.exitcode!=0 or not path.is_file():raise RuntimeError('Proceso sin resultado; revisar el registro local')
        return result_from_payload(json.loads(path.read_text(encoding='utf-8')))
    finally:
        if started and not tree.bound:
            # Failure before opening the gate cannot have provider descendants.
            if process.is_alive():process.terminate();process.join(5)
            if process.is_alive():process.kill();process.join(5)
            if process.is_alive():raise UnsafeProcessTree('El proceso bloqueado no cerró; no se cambia de conexión')
        tree.close() # Never returns while any owned process remains alive.
        if started and not process.is_alive():process.close()
