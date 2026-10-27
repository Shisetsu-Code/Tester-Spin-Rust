from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Iterable

from tester_spin.action_sanitize import copy_safe_diagnostics, sanitize_action_value
from tester_spin.models import Game, GameTestResult
from tester_spin.providers.bgaming import BGamingProvider
from tester_spin.scheduler import run_game_tests


def _fold(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def select_game(games: Iterable[Game], query: str) -> Game:
    items = list(games)
    needle = _fold(query)
    if not needle:
        raise ValueError("La consulta del juego está vacía.")

    exact: list[Game] = []
    for game in items:
        values = {_fold(game.name), _fold(game.slug), _fold(game.symbol)} - {""}
        if needle in values:
            exact.append(game)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"La consulta es ambigua: {query!r} coincide exactamente con {len(exact)} juegos.")

    partial: list[Game] = []
    for game in items:
        haystack = " ".join((_fold(game.name), _fold(game.slug), _fold(game.symbol)))
        if needle in haystack:
            partial.append(game)
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise ValueError(f"La consulta {query!r} no coincide con ningún juego del catálogo BGaming.")
    names = ", ".join(game.name for game in partial[:8])
    suffix = " …" if len(partial) > 8 else ""
    raise ValueError(
        f"La consulta es ambigua: {query!r} coincide con {len(partial)} juegos: {names}{suffix}"
    )


def write_result_summary(
    path: Path,
    result: GameTestResult,
    *,
    catalog_size: int,
    query: str,
) -> None:
    payload = {
        "schema": "spin-wire/action-bgaming-diagnostic/v1",
        "query": query,
        "catalog_size": int(catalog_size),
        "result": result.to_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_action_value(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ejecuta el adaptador BGaming real de Tester-Spin sin GUI para diagnóstico de GitHub Actions."
    )
    parser.add_argument("--game", required=True, help="Nombre, slug o identificador del juego.")
    parser.add_argument("--spins", type=int, default=1, help="Muestras por ruta; mínimo 1.")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout por operación en segundos.")
    parser.add_argument("--max-pages", type=int, default=100, help="Límite de páginas del catálogo.")
    parser.add_argument("--data-root", required=True, help="Directorio temporal de datos crudos; no se publica.")
    parser.add_argument("--output-dir", default="action-diagnostics", help="Directorio de evidencia sanitizada.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.spins < 1:
        raise SystemExit("--spins debe ser >= 1")
    if args.timeout < 1:
        raise SystemExit("--timeout debe ser >= 1")
    if args.max_pages < 1:
        raise SystemExit("--max-pages debe ser >= 1")

    output_dir = Path(args.output_dir).resolve()
    data_root = Path(args.data_root).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "spin-wire.log"

    def progress(message: str) -> None:
        text = str(sanitize_action_value(str(message)))
        print(text, flush=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    stop_event = threading.Event()
    provider = BGamingProvider(data_root)
    results: list[GameTestResult] = []

    try:
        progress("BGaming Actions: leyendo catálogo con el adaptador real de Tester-Spin.")
        games = provider.crawl_catalog(
            stop_event=stop_event,
            progress=progress,
            max_pages=args.max_pages,
        )
        game = select_game(games, args.game)
        progress(f"BGaming Actions: juego seleccionado={game.name!r}; iniciando una ejecución serial.")
        run_game_tests(
            provider,
            [game],
            concurrency=1,
            spins_per_game=args.spins,
            delay_between_starts_s=0.0,
            timeout_s=args.timeout,
            stop_event=stop_event,
            progress=progress,
            on_result=results.append,
        )
        if len(results) != 1:
            raise RuntimeError(f"Se esperaba un resultado y se recibieron {len(results)}.")
        result = results[0]
        write_result_summary(
            output_dir / "summary.json",
            result,
            catalog_size=len(games),
            query=args.game,
        )
        safe = []
        if result.run_dir:
            safe = copy_safe_diagnostics(Path(result.run_dir), output_dir)
        progress(
            f"BGaming Actions: estado={result.status}; "
            f"intentos={len(result.attempts)}; reportes_sanitizados={safe}."
        )
        return 0
    except BaseException as exc:
        detail = sanitize_action_value(f"{type(exc).__name__}: {exc}")
        failure = {
            "schema": "spin-wire/action-bgaming-diagnostic/v1",
            "query": args.game,
            "status": "INFRA_ERROR",
            "error": detail,
        }
        (output_dir / "summary.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        progress(f"BGaming Actions ERROR: {detail}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
