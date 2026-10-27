"""On-demand JSON-lines bridge. All writes belong to the new project."""
from __future__ import annotations

import contextlib
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
import threading

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA = (ROOT / CONFIG["data_dir"]).resolve()
if not DATA.is_relative_to(ROOT) or DATA == Path(CONFIG["source_data"]).resolve():
    raise RuntimeError("The engine must write only inside the new project")
os.chdir(ROOT)
os.environ["TESTER_SPIN_DATA_ROOT"] = str(DATA)
os.environ["TESTER_SPIN_APP_HOME"] = str(ROOT)
if CONFIG.get("playwright_browsers"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = CONFIG["playwright_browsers"]
OUTPUT = sys.stdout
LOCK = threading.Lock()


def emit(kind, **payload):
    with LOCK:
        OUTPUT.write(json.dumps({"event": kind, **payload}, ensure_ascii=False) + "\n")
        OUTPUT.flush()


class LogStream:
    def write(self, text):
        if text.strip():
            emit("log", text=text.strip())
        return len(text)

    def flush(self):
        pass


def seed_contract(provider, game, source_root=None, data_root=None):
    """Copy only execution contracts for a selected game, never old run captures."""
    source_root = Path(source_root or CONFIG["source_data"]).resolve()
    data_root = Path(data_root or DATA).resolve()
    directory = provider.farm_contract_dir(game)
    if directory is None:
        return 0
    directory = Path(directory).resolve()
    if not directory.is_relative_to(data_root):
        raise ValueError("Provider contract directory escaped local data")
    original = (source_root / directory.relative_to(data_root)).resolve()
    if not original.is_relative_to(source_root):
        raise ValueError("Original contract path escaped snapshot source")
    copied = 0
    for name in ("farm-contract.json", "sample-catalog.json", "mode-catalog.json"):
        source = original / name
        target = directory / name
        if source.is_file() and not target.exists() and source.stat().st_size <= 16 * 1024 * 1024:
            directory.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied += 1
    return copied


class Bridge:
    def __init__(self):
        self.worker = None
        self.stop = threading.Event()

    def dispatch(self, request):
        command = request.get("cmd")
        if command == "ping":
            from tester_spin.providers.registry import PROVIDERS
            emit("ready", providers={key: value[2] for key, value in PROVIDERS.items()}, data_root=str(DATA))
        elif command == "stop":
            self.stop.set()
            emit("log", text="Detención solicitada. Se conservarán las operaciones pendientes.")
        elif command == "shutdown":
            self.stop.set()
            return False
        elif command in {"run", "catalog"}:
            if self.worker is not None and self.worker.is_alive():
                emit("error", message="Ya hay una operación en ejecución")
            else:
                self.stop = threading.Event()
                self.worker = threading.Thread(target=self.execute, args=(request,), name="provider-operation")
                self.worker.start()
        else:
            emit("error", message="Operación desconocida")
        return True

    def execute(self, request):
        from tester_spin.models import GameTestResult
        from tester_spin.providers.registry import create_provider
        from tester_spin.scheduler import run_game_tests
        from tester_spin.storage import Storage

        provider_key = request.get("provider", "")
        done = 0
        try:
            with contextlib.redirect_stdout(LogStream()):
                storage = Storage(DATA / "tester-spin.sqlite3")
                provider = create_provider(provider_key, DATA)
                if request["cmd"] == "catalog":
                    catalog_options = dict(max_pages=10_000, stop_event=self.stop,
                                           progress=lambda text: emit("log", text=text))
                    parameters = inspect.signature(provider.crawl_catalog).parameters
                    if "timeout_s" in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
                        catalog_options["timeout_s"] = float(request.get("timeout", 30))
                    discovered = provider.crawl_catalog(**catalog_options)
                    # Catalog refresh adds/updates valid records; it never deletes old rows.
                    count = storage.upsert_games(list(discovered))
                    emit("done", operation="catalog", count=count, cancelled=self.stop.is_set())
                    return

                slugs = set(request.get("slugs", []))
                if not slugs:
                    raise ValueError("Seleccioná al menos un juego")
                games = [game for game in storage.list_games(provider_key) if game.slug in slugs]
                if len(games) != len(slugs):
                    raise ValueError("La selección contiene juegos que no están en el catálogo local")
                if request.get("dry_run") is True:
                    emit("plan", provider=provider_key, games=[g.slug for g in games], executed=False)
                    emit("done", operation="run", count=0, dry_run=True)
                    return
                for game in games:
                    seed_contract(provider, game)
                emit("started", provider=provider_key, total=len(games))

                def record(result: GameTestResult):
                    nonlocal done
                    storage.record_result(result)
                    done += 1
                    emit("result", provider=result.provider, slug=result.slug, status=result.status,
                         error=result.error, symbol=result.symbol, tested=result.finished_at,
                         success=result.successful_spins, failed=result.failed_spins, done=done, total=len(games))

                run_game_tests(provider, games,
                    concurrency=max(1, min(16, int(request.get("concurrency", 1)))),
                    spins_per_game=max(1, int(request.get("spins", 1))),
                    delay_between_starts_s=max(0, float(request.get("delay", 1))),
                    timeout_s=max(1, float(request.get("timeout", 30))),
                    stop_event=self.stop, progress=lambda text: emit("log", text=text), on_result=record,
                )
                emit("done", operation="run", count=done, total=len(games), cancelled=self.stop.is_set())
        except Exception as exc:
            emit("error", message=f"{type(exc).__name__}: {exc}")
            emit("done", operation=request["cmd"], count=done, failed=True, cancelled=self.stop.is_set())


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    bridge = Bridge()
    bridge.dispatch({"cmd": "ping"})
    try:
        for line in sys.stdin:
            try:
                if not bridge.dispatch(json.loads(line)):
                    break
            except (ValueError, TypeError) as exc:
                emit("error", message=str(exc))
    finally:
        bridge.stop.set()
        if bridge.worker is not None:
            bridge.worker.join()


if __name__ == "__main__":
    main()
