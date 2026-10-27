from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tester_spin.feature_filter import FILTERS, matches_features

from tkinter import filedialog, messagebox, ttk

from tester_spin.app_live import LiveTesterSpinApp
from tester_spin.catalog_maintenance import purge_provider_catalog_artifacts
from tester_spin.execution_backend import ExecutionConfig, LocalThreadExecutionBackend
from tester_spin.models import Game, GameTestResult
from tester_spin.mechanics import classify_mechanics, merge_mechanics, mechanics_badge, run_mechanics
from tester_spin.feature_summary import feature_summary, feature_table_counts
from tester_spin.ui_game_index import game_sort_key, retryable_games


class CurrentTesterSpinApp(LiveTesterSpinApp):
    """Current GUI with responsive event batching and pluggable execution backend."""

    _SORT_LABELS = {
        "name": "Nombre",
        "symbol": "ID proveedor",
        "status": "Estado",
        "tested": "Última prueba",
        "url": "Link",
        "purchases": "Cantidad de compras",
        "antebets": "Cantidad de antebets",
        "mechanics": "Mecánica particular",
    }
    _MAX_EVENTS_PER_TICK = 160
    _UI_DRAIN_BUDGET_S = 0.012

    def __init__(self) -> None:
        self._mechanics_index = {}
        self._feature_results = {}
        self._sort_column = "name"
        self._sort_reverse = False
        self._execution_backend = LocalThreadExecutionBackend()
        super().__init__()
        self.bind("<FocusIn>", self._refresh_external_results, add="+")
        from tester_spin.ui_layout import LayoutPreferences
        self._layout_preferences = LayoutPreferences(self, self.data_root / "ui-layout.json")
        def backfill():
            import json
            from pathlib import Path
            cache = self.data_root / "mechanics-index.json"
            try:
                try:
                    index = json.loads(cache.read_text(encoding="utf-8"))
                    if not isinstance(index, dict):
                        index = {}
                except (OSError, ValueError):
                    index = {}
                scans_path = self.data_root / "mechanics-scanned.json"
                try:
                    scanned = set(json.loads(scans_path.read_text(encoding="utf-8")))
                except (OSError, ValueError, TypeError):
                    scanned = set()
                runs = []
                for key, record in self.storage.mechanics_history(runs).items():
                    index[key] = merge_mechanics(index.get(key, {}), record)
                self._events.put(("mechanics_index", dict(index)))
                examined = 0
                for key, run_dir in runs:
                    if run_dir in scanned or not Path(run_dir).is_dir():
                        continue
                    index[key] = merge_mechanics(index.get(key, {}), run_mechanics({"run_dir": run_dir}))
                    scanned.add(run_dir)
                    examined += 1
                    if examined % 25 == 0:
                        self._events.put(("mechanics_index", dict(index)))
                temporary_scans = scans_path.with_suffix(".tmp")
                # Publish classification before marking its artifacts as scanned.

                self._events.put(("mechanics_index", index))
                temporary = cache.with_suffix(".tmp")
                temporary.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
                temporary.replace(cache)
                temporary_scans.write_text(json.dumps(sorted(scanned)), encoding="utf-8")
                temporary_scans.replace(scans_path)
            except (OSError, ValueError) as exc:
                self._events.put(("log", f"Índice de mecánicas incompleto: {exc}"))
        threading.Thread(target=backfill, daemon=True, name="mechanics-history").start()

    def _refresh_external_results(self, event) -> None:
        """Reload shared persisted results when returning to an idle window."""
        if event.widget is not self:
            return
        worker = getattr(self, "_worker", None)
        if worker is not None and worker.is_alive():
            return
        selection = self.tree.selection()
        position = self.tree.yview()
        self._refresh_games()
        remaining = [iid for iid in selection if self.tree.exists(iid)]
        if remaining:
            self.tree.selection_set(remaining)
        if position:
            self.tree.yview_moveto(position[0])

    def _build(self) -> None:
        super()._build()

        for column, label in self._SORT_LABELS.items():
            self.tree.heading(
                column,
                text=label,
                command=lambda selected=column: self._sort_by(selected),
            )
        self._update_sort_headings()

        filter_bar = ttk.Frame(self.test_all_btn.master.master)
        filter_bar.pack(fill="x", pady=(6,0))
        ttk.Label(filter_bar,text="Mostrar:").pack(side="left")
        self._feature_filter_var = tk.StringVar(self,value="Todos")
        self.feature_filter_combo = ttk.Combobox(filter_bar,textvariable=self._feature_filter_var,values=list(FILTERS),state="readonly",width=27)
        self.feature_filter_combo.pack(side="left",padx=(6,8))
        self.feature_filter_combo.bind("<<ComboboxSelected>>",lambda _:self._filter_changed())
        self.export_filtered_btn = ttk.Button(filter_bar,text="EXPORTAR FILTRADOS",command=self._export_filtered)
        self.export_filtered_btn.pack(side="left")

        controls = self.test_all_btn.master
        self.test_non_ok_btn = ttk.Button(
            controls,
            text="PROBAR NO OK",
            command=self._test_non_ok,
        )
        self.test_non_ok_btn.pack(side="left", padx=(8, 0))
        from tester_spin.failure_groups_ui import show_groups
        self.failure_groups_btn = ttk.Button(controls, text="GRUPOS / REPROBAR", command=lambda: show_groups(self))
        self.failure_groups_btn.pack(side="left", padx=(8, 0))
        self.export_partials_btn = ttk.Button(controls, text="EXPORTAR PARCIALES", command=self._export_partials)
        self.export_partials_btn.pack(side="left", padx=(8, 0))
        ttk.Label(
            controls,
            text=f"Ejecución: {self._execution_backend.display_name}",
        ).pack(side="left", padx=(14, 0))

        catalog_controls = self.crawl_btn.master
        self.export_catalog_btn = ttk.Button(
            catalog_controls, text="EXPORTAR CATÁLOGO TXT", command=self._export_catalog,
        )
        self.export_catalog_btn.pack(side="left", padx=(8, 0))
        self.delete_catalog_selected_btn = ttk.Button(
            catalog_controls,
            text="BORRAR SELECCIONADOS",
            command=self._delete_selected_from_catalog,
        )
        self.delete_catalog_selected_btn.pack(side="left", padx=(8, 0))
        self.clear_catalog_btn = ttk.Button(
            catalog_controls,
            text="VACIAR CATÁLOGO",
            command=self._clear_provider_catalog,
        )
        self.clear_catalog_btn.pack(side="left", padx=(8, 0))

    def _set_busy(self, busy: bool) -> None:
        super()._set_busy(busy)
        if hasattr(self, "failure_groups_btn"):
            self.failure_groups_btn.configure(state="disabled" if busy else "normal")
        if hasattr(self, "export_partials_btn"):
            self.export_partials_btn.configure(state="disabled" if busy else "normal")
        if hasattr(self, "test_non_ok_btn"):
            self.test_non_ok_btn.configure(state="disabled" if busy else "normal")
        if hasattr(self, "delete_catalog_selected_btn"):
            self.delete_catalog_selected_btn.configure(state="disabled" if busy else "normal")
        if hasattr(self, "clear_catalog_btn"):
            self.clear_catalog_btn.configure(state="disabled" if busy else "normal")

    def _delete_selected_from_catalog(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Tester-Spin", "Seleccioná uno o más juegos para borrar del catálogo.")
            return

        provider = self._provider()
        games = [self._games[item_id] for item_id in selection if item_id in self._games]
        if not games:
            return

        preview = "\n".join(f"• {game.name} [{game.slug}]" for game in games[:8])
        if len(games) > 8:
            preview += f"\n… y {len(games) - 8} más"

        if not messagebox.askyesno(
            "Tester-Spin",
            (
                f"¿Borrar {len(games)} juego(s) del catálogo de {provider.display_name}?\n\n"
                f"{preview}\n\n"
                "Quedarán EXCLUIDOS manualmente para que un próximo crawl/fallback "
                "no los vuelva a insertar. El historial de pruebas y sus artefactos "
                "no se borran."
            ),
        ):
            return

        blocked = self.storage.exclude_games(
            provider.key,
            {game.slug for game in games},
            reason="manual_gui",
        )
        self._append_log(
            f"Catálogo {provider.display_name}: exclusiones manuales añadidas={blocked}."
        )
        self.status_var.set(f"Eliminados del catálogo: {blocked}")
        self._refresh_games()

    def _filtered_export_games(self,provider_key):
        games=self.storage.list_games(provider_key)
        mode=FILTERS.get(self._feature_filter_var.get(),"all") if hasattr(self,"_feature_filter_var") else "all"
        if mode=="all":return games
        results={row.get('slug'):row for row in self.storage.latest_results(provider_key)}
        return [g for g in games if matches_features(results.get(g.slug,{}),mode)]

    def _export_catalog(self) -> None:
        """Export every persisted game of the selected provider, without UI filters."""
        from pathlib import Path
        from datetime import datetime
        from tester_spin.partial_export import write_game_export
        provider = self._provider()
        games = self.storage.list_games(provider.key)
        if not games:
            messagebox.showinfo("Exportar catálogo", "Este proveedor no tiene juegos cargados.", parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self, title=f"Exportar catálogo de {provider.display_name}",
            initialdir=str(Path.home() / "Desktop"),
            initialfile=f"catalogo-{provider.key}-{datetime.now():%Y%m%d-%H%M%S}.txt",
            defaultextension=".txt", filetypes=[("Archivo de texto", "*.txt")],
        )
        if not target:
            return
        try:
            count = write_game_export(target, games)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Exportar catálogo", str(exc), parent=self)
            return
        self.status_var.set(f"Exportados {count} enlaces del catálogo")
        self._append_log(f"Catálogo de {provider.display_name}: {count} enlaces exportados a {target}")
        messagebox.showinfo("Exportar catálogo", f"Exportados {count} enlaces, uno por línea.\n\n{target}", parent=self)

    def _export_filtered(self):
        from pathlib import Path
        from datetime import datetime
        from tester_spin.partial_export import write_game_export
        provider=self._provider()
        games=self._filtered_export_games(provider.key)
        if not games:
            messagebox.showinfo("Exportar filtrados","No hay juegos que coincidan con el filtro.",parent=self)
            return
        target=filedialog.asksaveasfilename(parent=self,title=f"Exportar {len(games)} juegos filtrados",initialdir=str(Path.home()/"Desktop"),initialfile=f"filtrados-{provider.key}-{datetime.now():%Y%m%d-%H%M%S}.txt",defaultextension=".txt",filetypes=[("Lista para Fuzzer manual","*.txt")])
        if not target:return
        try:count=write_game_export(target,games)
        except (OSError,ValueError) as exc:
            messagebox.showerror("Exportar filtrados",str(exc),parent=self)
            return
        self.status_var.set(f"Exportados {count} juegos filtrados")
        self._append_log(f"Exportados {count} juegos filtrados de {provider.display_name}: {target}")
        messagebox.showinfo("Exportar filtrados",f"Exportados {count} juegos para importar en Fuzzer manual.",parent=self)

    def _export_partials(self) -> None:
        from datetime import datetime
        from pathlib import Path
        from tester_spin.partial_export import partial_urls, write_partial_export
        provider = self._provider()
        games = CurrentTesterSpinApp._filtered_export_games(self,provider.key)
        try:
            urls = partial_urls(games)
        except ValueError as exc:
            messagebox.showerror("Exportar parciales", str(exc), parent=self)
            return
        if not urls:
            messagebox.showinfo("Exportar parciales", "Este proveedor no tiene juegos con estado PARCIAL.", parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self, title=f"Exportar {len(urls)} parciales de {provider.display_name}",
            initialdir=str(Path.home() / "Desktop"),
            initialfile=f"parciales-{provider.key}-{datetime.now():%Y%m%d-%H%M%S}.txt",
            defaultextension=".txt", filetypes=[("Lista para Fuzzer manual", "*.txt")],
        )
        if not target:
            return
        try:
            count = write_partial_export(target, games)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Exportar parciales", str(exc), parent=self)
            return
        self._append_log(f"Exportados {count} parciales de {provider.display_name}: {target}")
        self.status_var.set(f"Exportados {count} parciales para Fuzzer manual")
        messagebox.showinfo("Exportar parciales", f"Exportados {count} juegos.\n\nEn Fuzzer manual: Importar URLs → cargar el archivo TXT.", parent=self)

    def _clear_provider_catalog(self) -> None:
        provider = self._provider()
        games = self.storage.list_games(provider.key)
        exclusions = self.storage.list_catalog_exclusions(provider.key)

        if not messagebox.askyesno(
            "Tester-Spin",
            (
                f"¿VACIAR COMPLETAMENTE el catálogo de {provider.display_name}?\n\n"
                f"Filas actuales: {len(games)}\n"
                f"Exclusiones manuales: {len(exclusions)}\n\n"
                "Se borrarán las filas del catálogo, las exclusiones manuales y la "
                "metadata/miniaturas usadas para reconstruir el catálogo.\n\n"
                "SE CONSERVAN test_results y las carpetas tests/ de cada juego."
            ),
        ):
            return

        removed, cleared_exclusions = self.storage.clear_provider_catalog(
            provider.key,
            clear_exclusions=True,
        )
        stats = purge_provider_catalog_artifacts(provider.provider_root)
        self._append_log(
            f"RESET catálogo {provider.display_name}: filas={removed}, "
            f"exclusiones={cleared_exclusions}, archivos={stats.files_removed}, "
            f"directorios catálogo={stats.directories_removed}. Historial de pruebas preservado."
        )
        self.status_var.set(f"Catálogo vacío: {provider.display_name}")
        self._refresh_games()

    def _test_non_ok(self) -> None:
        provider = self._provider()
        games = retryable_games(self.storage.list_games(provider.key))
        if not games:
            messagebox.showinfo(
                "Tester-Spin",
                "No hay juegos reintentables: los restantes están OK o SIN_DEMO.",
            )
            return

        counts: dict[str, int] = {}
        for game in games:
            status = str(game.display_status or "PENDIENTE").strip().upper() or "PENDIENTE"
            counts[status] = counts.get(status, 0) + 1
        detail = ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
        if not messagebox.askyesno(
            "Tester-Spin",
            f"¿Probar los {len(games)} juegos que no están OK?\n\n{detail}",
        ):
            return
        self._start_tests(games)

    def _start_tests(self, games: list[Game]) -> None:
        """Start one orchestration thread; the backend owns the worker pool.

        Tk never performs provider I/O, waits on futures, or writes result rows.
        This boundary is intentionally transport-neutral so a remote execution
        backend can later replace LocalThreadExecutionBackend.
        """
        if self._worker and self._worker.is_alive():
            return
        try:
            config = ExecutionConfig(
                concurrency=max(1, int(self.concurrency_var.get())),
                spins_per_game=max(1, int(self.spins_var.get())),
                delay_between_starts_s=max(0.0, float(self.delay_var.get())),
                timeout_s=max(1.0, float(self.timeout_var.get())),
            )
            operation_delay_s = float(self.operation_delay_var.get().replace(",", "."))
            import math
            if not math.isfinite(operation_delay_s) or operation_delay_s < 0:
                raise ValueError("Delay entre operaciones inválido")
        except ValueError:
            messagebox.showerror("Tester-Spin", "Revisá concurrencia, repeticiones, delays y timeout.")
            return

        provider = self._provider()
        if provider.key == "ka_gaming":
            from tester_spin.providers.ka_gaming.limits import REQUEST_GATE
            REQUEST_GATE.configure_delay(operation_delay_s)
        requested_concurrency = config.concurrency
        effective_concurrency = provider.effective_test_concurrency(requested_concurrency)
        if effective_concurrency != requested_concurrency:
            config = ExecutionConfig(
                concurrency=effective_concurrency,
                spins_per_game=config.spins_per_game,
                delay_between_starts_s=config.delay_between_starts_s,
                timeout_s=config.timeout_s,
            )
        self._stop_event = threading.Event()
        self._test_total = len(games)
        self._test_done = 0
        self._set_busy(True)
        self.status_var.set(f"Probando 0/{len(games)}...")
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=max(1, len(games)), value=0)
        self._append_log(
            f"=== INICIO: proveedor={provider.display_name}, backend={self._execution_backend.key}, "
            f"juegos={len(games)}, simultáneos={config.concurrency}"
            + (
                f" (solicitados={requested_concurrency}, limitado por proveedor)"
                if config.concurrency != requested_concurrency
                else ""
            )
            + ", "
            f"repeticiones/modo={config.spins_per_game}, "
            f"delay={config.delay_between_starts_s}s, delay operaciones KA={operation_delay_s}s ==="
        )

        batch_results = []

        def on_result(result: GameTestResult) -> None:
            batch_results.append(result)
            # Persistence is intentionally outside Tk's main thread.
            self.storage.record_result(result)
            self._events.put(("test_result", result))

        def orchestrator() -> None:
            baseline = None
            try:
                baseline = self.storage.latest_results(provider.key)
                self._execution_backend.run(
                    provider,
                    games,
                    config=config,
                    stop_event=self._stop_event,
                    progress=lambda message: self._events.put(("log", message)),
                    on_result=on_result,
                )
            except Exception as exc:
                self._events.put(("error", f"Pruebas: {type(exc).__name__}: {exc}"))
            finally:
                from tester_spin.manual_review import write_review
                try:
                    report = write_review(batch_results, self.data_root / "reports", expected_count=len(games), baseline=baseline)
                    self._events.put(("log", f"Grupos y prioridades: {report.with_suffix('.groups.md')}"))
                    self._events.put(("manual_review", report))
                except OSError as exc:
                    self._events.put(("log", f"No se pudo guardar la revisión y los grupos: {exc}"))
                self._events.put(("tests_done", None))

        self._worker = threading.Thread(
            target=orchestrator,
            daemon=True,
            name="execution-orchestrator",
        )
        self._worker.start()

    def _sort_by(self, column: str) -> None:
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = column == "tested"
        self._apply_current_sort()
        self._update_sort_headings()

    def _update_sort_headings(self) -> None:
        for column, label in self._SORT_LABELS.items():
            suffix = ""
            if column == self._sort_column:
                suffix = " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(
                column,
                text=label + suffix,
                command=lambda selected=column: self._sort_by(selected),
            )

    def _apply_current_sort(self) -> None:
        mode = FILTERS.get(self._feature_filter_var.get(),"all") if hasattr(self,"_feature_filter_var") else "all"
        for iid, game in self._games.items():
            if not self.tree.exists(iid):continue
            if matches_features(self._feature_results.get(iid,{}),mode):
                self.tree.move(iid,"","end")
            else:
                self.tree.detach(iid)
        rows: list[tuple[str, Game]] = []
        for iid in self.tree.get_children(""):
            game = self._games.get(iid)
            if game is not None:
                rows.append((iid, game))

        for iid, game in rows:
            counts = feature_table_counts(self._feature_results.get(iid, {}))
            self.tree.set(iid, 'purchases', '—' if counts[0] is None else counts[0])
            self.tree.set(iid, 'antebets', '—' if counts[1] is None else counts[1])
            self.tree.set(iid, 'mechanics', mechanics_badge(merge_mechanics(self._mechanics_index.get(iid, {}), classify_mechanics(self._feature_results.get(iid, {})))))
        if self._sort_column in {'purchases', 'antebets'}:
            index = 0 if self._sort_column == 'purchases' else 1
            known, unknown = [], []
            for item in rows:
                count = feature_table_counts(self._feature_results.get(item[0], {}))[index]
                (unknown if count is None else known).append((item, count))
            known.sort(key=lambda value: (value[1], value[0][1].name.casefold()), reverse=self._sort_reverse)
            unknown.sort(key=lambda value: value[0][1].name.casefold())
            ordered = [item for item, _count in known + unknown]
        elif self._sort_column == "mechanics":
            ordered = sorted(rows, key=lambda item: (self.tree.set(item[0], "mechanics").casefold(), item[1].name.casefold()), reverse=self._sort_reverse)
        elif self._sort_column == "tested":
            tested = [(iid, game) for iid, game in rows if str(game.last_test_at or "").strip()]
            untested = [(iid, game) for iid, game in rows if not str(game.last_test_at or "").strip()]
            tested.sort(
                key=lambda item: game_sort_key(item[1], "tested"),
                reverse=self._sort_reverse,
            )
            untested.sort(key=lambda item: game_sort_key(item[1], "name"))
            ordered = tested + untested
        else:
            ordered = sorted(
                rows,
                key=lambda item: game_sort_key(item[1], self._sort_column),
                reverse=self._sort_reverse,
            )

        for position, (iid, _game) in enumerate(ordered):
            self.tree.move(iid, "", position)

    def _update_count_summary(self) -> None:
        counts = {
            "OK": 0,
            "OK MANUAL": 0,
            "PARCIAL": 0,
            "ERROR": 0,
            "SIN_DEMO": 0,
            "PENDIENTE": 0,
        }
        visible = [self._games[iid] for iid in self.tree.get_children("") if iid in self._games]
        for game in visible:
            status = str(game.display_status or "PENDIENTE").strip().upper() or "PENDIENTE"
            if status not in counts:
                status = "PENDIENTE"
            counts[status] += 1
        self.count_var.set(
            f"{len(visible)} de {len(self._games)} juegos | OK {counts['OK']} | "
            f"OK manual {counts['OK MANUAL']} | PARCIAL {counts['PARCIAL']} | ERROR {counts['ERROR']} | "
            f"SIN_DEMO {counts['SIN_DEMO']} | "
            f"PENDIENTE {counts['PENDIENTE']}"
        )

    def _filter_changed(self) -> None:
        # Filtering is a view operation; no database reads or image reloads.
        self._apply_current_sort()
        self._update_count_summary()

    def _refresh_games(self) -> None:
        if not self.provider_var.get() or self.provider_var.get() not in self._display_to_key:
            return
        self._feature_results = {
            f"{row.get('provider')}::{row.get('slug')}": row
            for row in self.storage.latest_results(self._provider().key)
        }
        # Detached rows also need deleting before the provider reloads identities.
        for iid in list(self._games):
            if self.tree.exists(iid):self.tree.delete(iid)
        super()._refresh_games()
        self._apply_current_sort()
        self._update_sort_headings()
        self._update_count_summary()

    def _upsert_catalog_game(self, game: Game) -> None:
        super()._upsert_catalog_game(game)
        self._apply_current_sort()
        self._update_count_summary()

    def _drain_events(self) -> None:
        """Drain with a hard item/time budget so Tk always regains control.

        Worker throughput can be much higher than UI rendering throughput, especially
        once execution is remote.  Never empty an unbounded producer queue in one Tk
        callback.  Batch text writes and table re-sorts once per UI slice.
        """
        started = time.monotonic()
        processed = 0
        log_lines: list[str] = []
        table_dirty = False
        full_refresh = False

        while processed < self._MAX_EVENTS_PER_TICK:
            if time.monotonic() - started >= self._UI_DRAIN_BUDGET_S:
                break
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                break
            processed += 1

            if kind in ("hardfire_opened", "hardfire_error"):
                log_lines.append(self._finish_hardfire_open(kind,value))
            elif kind == "catalog_game":
                # Stream the discovered Game directly. This avoids a storage round
                # trip per catalogue item, which is especially important for D1.
                if isinstance(value, Game):
                    LiveTesterSpinApp._upsert_catalog_game(self, value)
                    table_dirty = True
                else:
                    provider_key, slug = value  # type: ignore[misc]
                    game = self.storage.get_game(str(provider_key), str(slug))
                    if game is not None:
                        LiveTesterSpinApp._upsert_catalog_game(self, game)
                        table_dirty = True
            elif kind == "mechanics_index":
                for key, record in value.items():
                    self._mechanics_index[key] = merge_mechanics(self._mechanics_index.get(key, {}), record)
                table_dirty = True
            elif kind == "log":
                log_lines.append(str(value))
            elif kind == "catalog_done":
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=100, value=100)
                self._set_busy(False)
                self.status_var.set(f"Catálogo actualizado: {value} juegos")
                full_refresh = True
            elif kind == "test_result":
                result = value
                if isinstance(result, GameTestResult):
                    self._test_done += 1
                    self.progress.configure(value=self._test_done)
                    self.status_var.set(f"Probando {self._test_done}/{self._test_total}...")

                    responded = sum(1 for attempt in result.attempts if attempt.ok)
                    completed = sum(1 for attempt in result.attempts if attempt.ok and attempt.terminal)
                    pending = sum(1 for attempt in result.attempts if attempt.ok and not attempt.terminal)
                    errors = sum(1 for attempt in result.attempts if not attempt.ok)
                    errors += max(0, result.requested_spins - len(result.attempts))
                    log_lines.append(
                        f"[{result.game_name}] {result.status}: "
                        f"respondieron={responded}/{result.requested_spins}, "
                        f"completados={completed}/{result.requested_spins}, "
                        f"pendientes={pending}, errores={errors} | "
                        f"{feature_summary(result.to_dict())}"
                    )

                    # record_result() already committed in the orchestrator thread.
                    # Apply the authoritative result to the cached row instead of
                    # issuing a read-back query. This matters for remote D1.
                    iid = f"{result.provider}::{result.slug}"
                    self._feature_results[iid] = result.to_dict()
                    self._mechanics_index[iid] = merge_mechanics(self._mechanics_index.get(iid, {}), classify_mechanics(self._feature_results[iid]))
                    game = self._games.get(iid)
                    if game is not None:
                        game.symbol = result.symbol or game.symbol
                        game.manual_ok_at = ""
                        game.manual_ok_note = ""
                        game.last_status = result.status
                        game.last_error = result.error
                        game.last_test_at = result.finished_at
                        game.last_latency_ms = result.elapsed_ms
                        game.updated_at = result.finished_at
                        LiveTesterSpinApp._upsert_catalog_game(self, game)
                        table_dirty = True
            elif kind == "manual_review":
                self._show_manual_review(value)
                log_lines.append(f"Lista de revisión manual: {value}")
            elif kind == "tests_done":
                self._set_busy(False)
                self.status_var.set(f"Pruebas terminadas: {self._test_done}/{self._test_total}")
                self.progress.configure(value=self._test_total)
                full_refresh = True
            elif kind == "error":
                self.progress.stop()
                self._set_busy(False)
                self.status_var.set("Error")
                log_lines.append(str(value))
                messagebox.showerror("Tester-Spin", str(value))

        if log_lines:
            self._append_log("\n".join(log_lines))

        if full_refresh:
            self._refresh_games()
        elif table_dirty:
            self._apply_current_sort()
            self._update_sort_headings()
            self._update_count_summary()

        # Backlogged remote/local producers get fast incremental draining; when the
        # queue is quiet we reduce idle wakeups.
        self.after(15 if not self._events.empty() else 75, self._drain_events)

    def _show_manual_review(self, path) -> None:
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText
        from pathlib import Path
        window = tk.Toplevel(self)
        window.title("Juegos para revisar manualmente")
        window.geometry("900x650")
        text = ScrolledText(window, wrap="word", font=("Segoe UI", 11), padx=16, pady=16)
        text.pack(fill="both", expand=True)
        text.insert("1.0", Path(path).read_text(encoding="utf-8"))
        text.configure(state="disabled")
        ttk.Label(window, text=f"Guardado en: {path}", wraplength=860).pack(padx=12, pady=8)


def main() -> None:
    CurrentTesterSpinApp().mainloop()


if __name__ == "__main__":
    main()
