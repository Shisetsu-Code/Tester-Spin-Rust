from __future__ import annotations

import argparse
import json
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from tester_spin.action_bgaming_diagnostic import select_game
from tester_spin.action_sanitize import copy_safe_diagnostics, sanitize_action_value
from tester_spin.models import Game, GameTestResult
from tester_spin.providers import BGamingProvider
from tester_spin.scheduler import run_game_tests


@dataclass(frozen=True, slots=True)
class SweepConfig:
    concurrency: int
    spins: int
    timeout_seconds: float
    max_catalog_pages: int
    targets: tuple[str, ...]
    run_nonce: str = ""


def load_sweep_config(path: Path) -> SweepConfig:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"sweep config inválido: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("sweep config debe ser un objeto JSON")

    try:
        concurrency = int(payload.get("concurrency", 3))
        spins = int(payload.get("spins", 1))
        timeout_seconds = float(payload.get("timeout_seconds", 60.0))
        max_catalog_pages = int(payload.get("max_catalog_pages", 100))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"sweep config contiene valores numéricos inválidos: {exc}") from exc

    if concurrency < 1 or concurrency > 4:
        raise ValueError("concurrency debe estar entre 1 y 4")
    if spins < 1:
        raise ValueError("spins debe ser >= 1")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds debe ser >= 1")
    if max_catalog_pages < 1:
        raise ValueError("max_catalog_pages debe ser >= 1")

    raw_targets = payload.get("targets", ["*"])
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError("targets debe ser una lista no vacía")
    targets = tuple(str(value).strip() for value in raw_targets)
    if any(not value for value in targets):
        raise ValueError("targets no puede contener valores vacíos")
    if "*" in targets and targets != ("*",):
        raise ValueError("'*' sólo puede usarse como único target")

    return SweepConfig(
        concurrency=concurrency,
        spins=spins,
        timeout_seconds=timeout_seconds,
        max_catalog_pages=max_catalog_pages,
        targets=targets,
        run_nonce=str(payload.get("run_nonce") or "").strip(),
    )


def make_sweep_provider(data_root: Path, *, concurrency: int) -> BGamingProvider:
    """Use live runtime evidence first; capture HAR only in focused diagnostics."""
    return BGamingProvider(
        data_root,
        test_concurrency_cap=concurrency,
        capture_analysis_har=False,
    )


def resolve_sweep_games(games: Iterable[Game], targets: list[str]) -> list[Game]:
    items = list(games)
    if targets == ["*"]:
        return items
    if "*" in targets:
        raise ValueError("'*' sólo puede usarse como único target")

    selected: list[Game] = []
    seen: set[tuple[str, str]] = set()
    for query in targets:
        game = select_game(items, query)
        key = (game.provider, game.slug)
        if key in seen:
            continue
        seen.add(key)
        selected.append(game)
    return selected


def _safe_name(value: str) -> str:
    clean = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in str(value or "")
    ).strip("._")
    return clean[:160] or "game"


def _read_candidate(provider: BGamingProvider, game: Game) -> dict[str, Any]:
    game_dir = provider.farm_contract_dir(game)
    if game_dir is None:
        game_dir = provider.game_dir(game)
    path = Path(game_dir) / "analysis" / "farm-contract-candidate.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def build_sweep_record(
    provider: BGamingProvider,
    game: Game,
    result: GameTestResult,
) -> dict[str, Any]:
    candidate = _read_candidate(provider, game)
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    mode_keys = (
        "id",
        "kind",
        "observed",
        "validated",
        "executable",
        "coverage_required",
        "discovery_state",
        "evidence_level",
        "execution_state",
        "source",
    )
    modes: list[dict[str, Any]] = []
    for raw_mode in result.discovered_modes:
        if not isinstance(raw_mode, dict):
            continue
        modes.append(
            {
                key: sanitize_action_value(raw_mode.get(key))
                for key in mode_keys
                if key in raw_mode
            }
        )

    return sanitize_action_value(
        {
            "slug": result.slug or game.slug,
            "game_name": result.game_name or game.name,
            "symbol": result.symbol or game.symbol,
            "status": result.status,
            "successful_spins": int(result.successful_spins),
            "failed_spins": int(result.failed_spins),
            "error": result.error,
            "farm_ready": bool(candidate.get("ready")),
            "farm_unresolved": candidate.get("unresolved") or [],
            "protocol_family": str(source.get("protocol_family") or ""),
            "modes": modes,
        }
    )


def build_sweep_summary(
    *,
    catalog_size: int,
    selected_size: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    sorted_records = sorted(
        (dict(record) for record in records),
        key=lambda item: (
            str(item.get("status") or ""),
            str(item.get("game_name") or "").casefold(),
            str(item.get("slug") or ""),
        ),
    )
    counts = Counter(str(record.get("status") or "UNKNOWN") for record in sorted_records)
    status_counts = {key: counts[key] for key in sorted(counts)}
    ok_not_ready = sorted(
        str(record.get("slug") or "")
        for record in sorted_records
        if str(record.get("status") or "") == "OK" and not bool(record.get("farm_ready"))
    )
    return {
        "schema": "spin-wire/action-bgaming-sweep/v1",
        "catalog_size": int(catalog_size),
        "selected_size": int(selected_size),
        "completed_size": len(sorted_records),
        "status_counts": status_counts,
        "ok_not_ready_count": len(ok_not_ready),
        "ok_not_ready": ok_not_ready,
        "results": sorted_records,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_action_value(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fallback_game(result: GameTestResult) -> Game:
    return Game(
        provider=result.provider,
        slug=result.slug,
        name=result.game_name,
        url=result.game_url,
        symbol=result.symbol,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ejecuta un barrido BGaming completo o por cohortes usando el adaptador real de Tester-Spin."
    )
    parser.add_argument("--config", required=True, help="Archivo JSON de configuración del barrido.")
    parser.add_argument("--data-root", required=True, help="Directorio temporal de datos crudos; no se publica.")
    parser.add_argument("--output-dir", default="action-sweep", help="Directorio de evidencia sanitizada.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    data_root = Path(args.data_root).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "sweep.log"
    records: list[dict[str, Any]] = []
    catalog_size = 0
    selected_size = 0

    def progress(message: str) -> None:
        text = str(sanitize_action_value(str(message)))
        print(text, flush=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    def persist_summary() -> None:
        _write_json(
            output_dir / "summary.json",
            build_sweep_summary(
                catalog_size=catalog_size,
                selected_size=selected_size,
                records=records,
            ),
        )

    stop_event = threading.Event()

    try:
        config = load_sweep_config(Path(args.config))
        provider = make_sweep_provider(data_root, concurrency=config.concurrency)
        progress(
            f"BGaming sweep: catálogo, concurrency={config.concurrency}, "
            f"spins={config.spins}, targets={list(config.targets)!r}."
        )
        games = provider.crawl_catalog(
            stop_event=stop_event,
            progress=progress,
            max_pages=config.max_catalog_pages,
        )
        catalog_size = len(games)
        if not provider.catalog_crawl_authoritative:
            raise RuntimeError(
                "BGaming sweep requiere un catálogo autoritativo: "
                + str(provider.catalog_crawl_reason or "razón no informada")
            )

        selected = resolve_sweep_games(games, list(config.targets))
        selected_size = len(selected)
        by_slug = {game.slug: game for game in selected}
        persist_summary()

        def on_result(result: GameTestResult) -> None:
            game = by_slug.get(result.slug) or _fallback_game(result)
            record = build_sweep_record(provider, game, result)
            records.append(record)
            safe_slug = _safe_name(result.slug or game.slug or game.name)
            _write_json(output_dir / "results" / f"{safe_slug}.json", record)
            if (
                str(result.status or "") != "OK"
                or not bool(record.get("farm_ready"))
            ) and result.run_dir:
                copy_safe_diagnostics(
                    Path(result.run_dir),
                    output_dir / "games" / safe_slug,
                )
            persist_summary()
            progress(
                f"BGaming sweep: {result.game_name!r} => {result.status}; "
                f"farm_ready={bool(record.get('farm_ready'))}; "
                f"completados={len(records)}/{selected_size}."
            )

        run_game_tests(
            provider,
            selected,
            concurrency=config.concurrency,
            spins_per_game=config.spins,
            delay_between_starts_s=0.25,
            timeout_s=config.timeout_seconds,
            stop_event=stop_event,
            progress=progress,
            on_result=on_result,
        )
        if len(records) != selected_size:
            raise RuntimeError(
                f"barrido incompleto: seleccionados={selected_size}, completados={len(records)}"
            )
        persist_summary()
        progress(
            f"BGaming sweep terminado: catálogo={catalog_size}, "
            f"seleccionados={selected_size}, completados={len(records)}."
        )
        return 0
    except BaseException as exc:
        detail = sanitize_action_value(f"{type(exc).__name__}: {exc}")
        failure = build_sweep_summary(
            catalog_size=catalog_size,
            selected_size=selected_size,
            records=records,
        )
        failure["status"] = "INFRA_ERROR"
        failure["error"] = detail
        _write_json(output_dir / "summary.json", failure)
        progress(f"BGaming sweep ERROR: {detail}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
