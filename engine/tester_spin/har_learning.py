"""Optional local Aislador worker. No dynamic primitive/code installation."""
import json,os,subprocess,sys,threading,sqlite3
from contextlib import closing
from pathlib import Path

_lock=threading.Lock()
_workers={}


def configuration(data_root):
    path=Path(data_root)/"har-learning.json"
    if not path.is_file():return None
    config=json.loads(path.read_text(encoding="utf-8"))
    if config.get("enabled") is not True:return None
    source=Path(config.get("aislador_root",""))
    if not source.is_absolute() or not (source/"aislador/__main__.py").is_file():raise ValueError("Configurá la instalación local de Aislador")
    return config,source


def _reap(process,database,root):
    try:
        if process.wait()!=0:return
        state=root/"har-learning/failures.private.json"
        if not state.is_file():return
        cursor=json.loads(state.read_text(encoding="utf-8"))["cursor"]
        with closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True)) as con:
            latest=con.execute("SELECT COALESCE(MAX(id),0) FROM test_results WHERE status IN ('ERROR','PARCIAL')").fetchone()[0]
        if latest>cursor:kick_worker(database)
    except Exception:pass


def kick_worker(database):
    database=Path(database).resolve();root=database.parent
    try:
        configured=configuration(root)
        if configured is None:return False
        config,source=configured;key=str(database)
        with _lock:
            existing=_workers.get(key)
            if existing is not None and existing.poll() is None:return True
            out=root/"har-learning";out.mkdir(parents=True,exist_ok=True)
            command=[config.get("python") or sys.executable,"-m","aislador","follow-failures",
                "--tester-spin-db",str(database),"--out",str(out),"--after-id",str(int(config.get("after_id",0))),
                "--seconds",str(int(config.get("seconds",12)))]
            with (out/"worker.private.log").open("a",encoding="utf-8") as log:
                _workers[key]=subprocess.Popen(command,cwd=source,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
            threading.Thread(target=_reap,args=(_workers[key],database,root),daemon=True,name="har-capture-reap").start()
            return True
    except Exception as exc:
        # Recording a game result must not fail because an optional learner is absent.
        try:
            out=root/"har-learning";out.mkdir(parents=True,exist_ok=True)
            (out/"launcher-error.txt").write_text(str(exc),encoding="utf-8")
        except OSError:pass
        return False


def inspect_capture(har):
    """Diagnose a saved capture before optional external filtering; no replay."""
    import re
    from urllib.parse import urlsplit
    from tester_spin.har_capture_diagnostics import capture_entries
    har=Path(har).resolve()
    if not har.is_file() or har.suffix.casefold()!='.har':
        raise ValueError('No se encontró el HAR guardado')
    if har.stat().st_size > 256*1024*1024:
        raise ValueError('HAR_TOO_LARGE: el límite de análisis es 256 MiB.')
    try:
        document=json.loads(har.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError):
        raise ValueError('HAR_INVALID_JSON: exportá nuevamente el HAR con contenido.') from None
    entries=capture_entries(document)
    if not entries and not document['log'].get('_warpWebSockets'):
        raise ValueError('HAR_EMPTY_CAPTURE: iniciá la grabación antes de recargar la demo y exportá con contenido después de cerrar la ronda.')
    codes=set()
    for entry in entries:
        try: url=urlsplit(entry.get('request',{}).get('url',''))
        except ValueError: continue
        if url.scheme=='https' and url.hostname=='cachedownload.playtechone.com':
            match=re.match(r'/ngmdistributed/ngm-(?:desktop|mobile)/[^/]+/([A-Za-z0-9_]+)/',url.path)
            if match: codes.add(match[1])
    if len(codes)==1:
        from tester_spin.providers.playtech.ngm_contracts import analyze_har
        report=analyze_har(document,next(iter(codes)))
        return dict(report['capture_diagnostics'], contract_issues=report['unresolved'])
    return dict(entry_count=len(entries), issues=[], next_steps=[])


def isolate_capture(har,data_root):
    diagnostic=inspect_capture(har)
    guidance='; '.join(diagnostic.get('issues',[])+diagnostic.get('contract_issues',[])+diagnostic['next_steps'])
    configured=configuration(data_root)
    if configured is None:
        raise ValueError((guidance+' · ' if guidance else '')+'Aislador no está configurado para este programa; el análisis local no cambia la cobertura del juego.')
    config,source=configured;har=Path(har).resolve()
    command=[config.get("python") or sys.executable,"-m","aislador","extract",str(har),"--provider","auto",
             "--out",str(Path(data_root).resolve()/"har-learning/manual"),"--json"]
    completed=subprocess.run(command,cwd=source,capture_output=True,text=True,encoding="utf-8",timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    if completed.returncode:
        raise ValueError((guidance+' · ' if guidance else '')+(completed.stderr.strip() or "No se pudo filtrar el HAR"))
    result=json.loads(completed.stdout)
    if isinstance(result,list):
        for row in result:
            if isinstance(row,dict):row['capture_diagnostics']=diagnostic
    return result
