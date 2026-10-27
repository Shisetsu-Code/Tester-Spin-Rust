from __future__ import annotations

import threading
import time
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections.abc import Callable, Iterable

from tester_spin.farm_contract import export_farm_contract
from tester_spin.models import Game, GameTestResult
from tester_spin.providers.base import ProviderAdapter

Progress = Callable[[str], None]
ResultCallback = Callable[[GameTestResult], None]


def run_game_tests(
    provider: ProviderAdapter,
    games: Iterable[Game],
    *,
    concurrency: int,
    spins_per_game: int,
    delay_between_starts_s: float,
    timeout_s: float,
    stop_event: threading.Event,
    progress: Progress,
    on_result: ResultCallback,
) -> None:
    queue = list(games)
    if not queue:
        return

    requested_concurrency = max(1, int(concurrency))
    concurrency = provider.effective_test_concurrency(requested_concurrency)
    if concurrency != requested_concurrency:
        progress(
            f"{provider.display_name}: concurrencia solicitada={requested_concurrency}, "
            f"límite seguro del proveedor={concurrency}; se ejecutará en serie."
        )
    spins_per_game = max(1, int(spins_per_game))
    delay_between_starts_s = max(0.0, float(delay_between_starts_s),
                                 float(getattr(provider, "min_game_start_interval_s", 0.0)))
    timeout_s = max(1.0, float(timeout_s))

    def execute(game: Game, game_progress: Progress) -> GameTestResult:
        try:
            provider.prepare_test_artifacts(
                game,
                timeout_s=timeout_s,
                stop_event=stop_event,
                progress=game_progress,
            )
        except Exception as exc:
            # Diagnostic preparation is best-effort and must never turn an
            # otherwise valid provider test into an ERROR.
            game_progress(
                f"preparación de artefactos ERROR; la prueba continúa: "
                f"{type(exc).__name__}: {exc}"
            )
        if stop_event.is_set():
            return GameTestResult(
                provider=game.provider,
                slug=game.slug,
                game_name=game.name,
                game_url=game.url,
                requested_spins=spins_per_game,
                successful_spins=0,
                failed_spins=spins_per_game,
                status="CANCELADO",
                symbol=game.symbol,
                error="Detención solicitada durante preparación de artefactos.",
            )
        result = provider.test_game(
            game,
            spins=spins_per_game,
            timeout_s=timeout_s,
            stop_event=stop_event,
            progress=game_progress,
        )
        result.samples_per_path = spins_per_game
        try:
            from tester_spin.coverage_history import retain_pending_branches
            retain_pending_branches(provider.farm_contract_dir(game), result)
            result = provider.finalize_test_result(result, progress=game_progress)
            export_farm_contract(provider, game, result, progress=game_progress)
        except Exception as exc:
            # Keep the provider result and its captures when postprocessing fails.
            result.status = "ERROR"
            result.error = (result.error + f" Postprocesamiento: {type(exc).__name__}: {exc}").strip()
            game_progress(result.error)
        return result

    def worker(game: Game) -> GameTestResult:
        import traceback
        from tester_spin.run_diagnostics import write_run_diagnostics
        from tester_spin.run_journal import RunJournal

        journal = None
        try:
            journal = RunJournal(provider.farm_contract_dir(game), game)
            journal.note("CONFIG", {"spins_per_game": spins_per_game, "timeout_s": timeout_s,
                                    "concurrency": concurrency, "delay_between_starts_s": delay_between_starts_s,
                                    "response_observation": "structure-and-state/v1", "return_to_base_required": 2, "return_to_base_max_probes": 10})
        except OSError as exc:
            progress(f"[{game.name}] No se pudo iniciar el registro de diagnóstico: {exc}")

        def game_progress(message: str) -> None:
            if journal is not None:
                try:
                    journal.note("PROGRESS", message)
                except OSError as exc:
                    progress(f"[{game.name}] Error guardando diagnóstico: {exc}")
            progress(f"[{game.name}] {message}")

        failed_before_result = False
        try:
            from tester_spin.return_to_base import audit_scope
            with audit_scope(stop_event):
                result = execute(game, game_progress)
        except Exception as exc:
            failed_before_result = True
            result = GameTestResult(
                provider=game.provider, slug=game.slug, game_name=game.name,
                game_url=game.url, requested_spins=spins_per_game,
                successful_spins=0, failed_spins=spins_per_game,
                status="ERROR", symbol=game.symbol,
                error=f"{type(exc).__name__}: {exc}",
            )
            if journal is not None:
                try:
                    journal.note("EXCEPTION", {"error": result.error, "traceback": traceback.format_exc()})
                except OSError:
                    pass
        if not result.run_dir and journal is not None and journal.path is not None:
            result.run_dir = str(journal.path.parent)
            result.samples_per_path = spins_per_game
            if failed_before_result:
                try:
                    result = provider.finalize_test_result(result, progress=game_progress)
                except Exception as exc:
                    result.error += f"; finalización: {type(exc).__name__}: {exc}"
        try:
            if journal is not None:
                journal.note("END", {"status": result.status, "run_dir": result.run_dir})
            write_run_diagnostics(result, journal_path=journal.path if journal else None)
            if result.run_dir:
                game_progress(f"Diagnóstico: {Path(result.run_dir) / 'diagnostic.md'}")
                import json
                observed = json.loads((Path(result.run_dir)/'server-observations.json').read_text(encoding='utf-8'))
                game_progress(f"Novedades de protocolo: {observed['protocol_changes']}; variaciones de resultado: {observed['outcome_variations']}; respuestas no legibles: {observed['unparsed']}; ramas pendientes: {observed.get('pending_branches', 0)}. Ver Respuestas nuevas en el árbol.")
        except (OSError, ValueError) as exc:
            message = f"Diagnóstico incompleto: {type(exc).__name__}: {exc}"
            if result.status == "OK":
                result.status = "PARCIAL"
            result.error = (result.error + " " + message).strip()
            game_progress(message)
        return result

    def deliver_result(result):
        from tester_spin.mechanics import run_mechanics
        try:
            result.mechanics = run_mechanics(result.to_dict())
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            progress(f"[{result.game_name}] Clasificación de mecánicas incompleta: {exc}")
        try:
            on_result(result)
        except Exception as exc:
            progress(f"[{result.game_name}] No se pudo registrar el resultado: {type(exc).__name__}: {exc}. "
                     f"La corrida continúa; capturas: {result.run_dir or 'sin carpeta'}")

    in_flight: dict[Future[GameTestResult], Game] = {}
    next_index = 0
    last_start = None

    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="game-test") as pool:
        while (next_index < len(queue) or in_flight) and not stop_event.is_set():
            while next_index < len(queue) and len(in_flight) < concurrency and not stop_event.is_set():
                if last_start is not None and delay_between_starts_s > 0:
                    remaining = delay_between_starts_s - (time.monotonic() - last_start)
                    if remaining > 0 and stop_event.wait(remaining):
                        break

                if stop_event.is_set():
                    break
                block_check = getattr(provider, "test_start_block_reason", None)
                block_reason = block_check(timeout_s=timeout_s) if block_check is not None else ""
                if block_reason:
                    progress(f"{provider.display_name}: {block_reason}")
                    stop_event.set()
                    break
                game = queue[next_index]
                next_index += 1
                progress(
                    f"Iniciando {next_index}/{len(queue)}: {game.name} "
                    f"(activos={len(in_flight) + 1}/{concurrency})"
                )
                future = pool.submit(worker, game)
                in_flight[future] = game
                last_start = time.monotonic()

            if not in_flight:
                continue

            done, _ = wait(tuple(in_flight), timeout=0.25, return_when=FIRST_COMPLETED)
            for future in done:
                game = in_flight.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = GameTestResult(
                        provider=game.provider,
                        slug=game.slug,
                        game_name=game.name,
                        game_url=game.url,
                        requested_spins=spins_per_game,
                        successful_spins=0,
                        failed_spins=spins_per_game,
                        status="ERROR",
                        symbol=game.symbol,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                deliver_result(result)

        if stop_event.is_set():
            progress("Detención solicitada; esperando las pruebas que ya estaban en vuelo...")
            for future, game in list(in_flight.items()):
                try:
                    result = future.result()
                except Exception as exc:
                    result = GameTestResult(
                        provider=game.provider,
                        slug=game.slug,
                        game_name=game.name,
                        game_url=game.url,
                        requested_spins=spins_per_game,
                        successful_spins=0,
                        failed_spins=spins_per_game,
                        status="CANCELADO",
                        symbol=game.symbol,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                deliver_result(result)
