from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageTk
from tester_spin.responsive_ui import FlowFrame

from tester_spin.firefox_launcher import open_firefox
from tester_spin.models import Game, GameTestResult
from tester_spin.providers.base import ProviderRegistry
from tester_spin.providers.registry import PROVIDERS, create_provider
from tester_spin.scheduler import run_game_tests
from tester_spin.storage import Storage


class TesterSpinApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Tester-Spin")
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(1500, max(800,screen_width-100))}x{min(940,max(640,screen_height-120))}")
        self.minsize(800, 640)
        icon = Path(__file__).with_name('assets') / 'tester-spin.ico'
        png_icon = icon.with_suffix('.png')
        if png_icon.exists():
            self._app_icon = tk.PhotoImage(file=str(png_icon))
            self.iconphoto(True, self._app_icon)
        if os.name == 'nt' and icon.exists():
            self.iconbitmap(str(icon))

        self.root_dir = Path.cwd()
        self.data_root = self.root_dir / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.storage = Storage(self.data_root / "tester-spin.sqlite3")

        self.registry = ProviderRegistry()
        from tester_spin.providers import selected_provider_keys
        selected = {'1spin4win' if key == 'one_spin4win' else key for key in selected_provider_keys()}
        unknown = selected - PROVIDERS.keys()
        if unknown:
            raise ValueError('Proveedores no registrados: ' + ', '.join(sorted(unknown)))
        for key in PROVIDERS:
            if selected and key not in selected:
                continue
            self.registry.register(create_provider(key,self.data_root))
        self._display_to_key = {provider.display_name: provider.key for provider in self.registry.all()}

        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._games: dict[str, Game] = {}
        self._thumb_images: dict[str, ImageTk.PhotoImage] = {}
        self._thumb_signatures = {}
        self._preview_image: ImageTk.PhotoImage | None = None
        self._preview_original = None
        self._preview_size = None
        self._test_total = 0
        self._test_done = 0
        self._hardfire_opening = False

        providers = list(self._display_to_key)
        self.provider_var = tk.StringVar(value=providers[0] if providers else "")
        self.catalog_url_var = tk.StringVar()
        self.max_pages_var = tk.StringVar(value="100")
        self.concurrency_var = tk.StringVar(value="3")
        self.spins_var = tk.StringVar(value="1")
        self.delay_var = tk.StringVar(value="1.0")
        self.operation_delay_var = tk.StringVar(value="0.2")
        self.timeout_var = tk.StringVar(value="30")
        self.status_var = tk.StringVar(value="Listo")
        self.count_var = tk.StringVar(value="0 juegos")
        self.selection_var = tk.StringVar(value="Sin selección")

        self._build()
        self._on_provider_changed()
        self.after(100, self._drain_events)

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        self.sections = ttk.Panedwindow(outer, orient="vertical")
        self.sections.pack(fill="both", expand=True)
        top = ttk.LabelFrame(self.sections, text="Proveedor y catálogo", padding=10)
        self.sections.add(top, weight=0)
        row = FlowFrame(top)
        row.pack(fill="x")

        provider_group = ttk.Frame(row)
        provider_group.pack(side="left")
        ttk.Label(provider_group, text="Proveedor:").pack(side="left")
        self.provider_combo = ttk.Combobox(
            provider_group,
            textvariable=self.provider_var,
            values=list(self._display_to_key),
            state="readonly",
            width=22,
        )
        self.provider_combo.pack(side="left", padx=(6, 14))
        self.provider_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_provider_changed())

        url_group = ttk.Frame(row)
        url_group._flow_expand = True
        url_group.pack(side="left")
        ttk.Label(url_group, text="URL catálogo:").pack(side="left")
        ttk.Entry(url_group, textvariable=self.catalog_url_var, width=24).pack(side="left", fill="x", expand=True, padx=(6,0))
        page_group = ttk.Frame(row)
        page_group.pack(side="left")
        ttk.Label(page_group, text="Máx. páginas:").pack(side="left")
        ttk.Entry(page_group, textvariable=self.max_pages_var, width=7).pack(side="left", padx=(6, 10))
        self.crawl_btn = ttk.Button(row, text="CARGAR / ACTUALIZAR CATÁLOGO", command=self._start_crawl)
        self.crawl_btn.pack(side="left")

        opts = ttk.LabelFrame(self.sections, text="Prueba de juegos", padding=10)
        self.sections.add(opts, weight=0)
        row2 = FlowFrame(opts)
        row2.pack(fill="x")

        for label, var, width in (
            ("Juegos simultáneos", self.concurrency_var, 7),
            ("Repeticiones por modo", self.spins_var, 7),
            ("Delay entre juegos (s)", self.delay_var, 7),
            ("Timeout (s)", self.timeout_var, 7),
        ):
            field = ttk.Frame(row2)
            field.pack(side="left")
            ttk.Label(field, text=label + ":").pack(side="left", padx=(0,5))
            ttk.Entry(field, textvariable=var, width=width).pack(side="left")

        operation_row = FlowFrame(opts)
        operation_row.pack(fill="x", pady=(8, 0))
        operation_group = ttk.Frame(operation_row)
        operation_group.pack(side="left")
        ttk.Label(operation_group, text="Delay entre operaciones KA (s):").pack(side="left", padx=(0, 5))
        ttk.Entry(operation_group, textvariable=self.operation_delay_var, width=7).pack(side="left")
        operation_note = ttk.Label(operation_row, text="Pausa entre operaciones KA. 0 desactiva la pausa; máximo 30 requests/s.")
        operation_note._flow_wrap = True
        operation_note.pack(side="left")

        self.test_selected_btn = ttk.Button(row2, text="PROBAR SELECCIONADOS", command=self._test_selected)
        self.test_selected_btn.pack(side="left", padx=(20, 8))
        self.test_all_btn = ttk.Button(row2, text="PROBAR TODOS", command=self._test_all)
        self.test_all_btn.pack(side="left")
        self.stop_btn = ttk.Button(row2, text="DETENER", command=self._stop, state="disabled")
        self.stop_btn.pack(side="right")

        help_label = ttk.Label(opts, text="Se prueban los modos conocidos de cada juego. Las compras o recorridos pendientes quedan como PARCIAL. Ctrl+C: copiar enlace y abrir en Firefox.")
        help_label.pack(fill="x", pady=(6,0))
        help_label.bind('<Configure>', lambda event: help_label.configure(wraplength=max(100,event.width)))

        status_row = FlowFrame(self.sections)
        self.sections.add(status_row, weight=0)
        status_label = ttk.Label(status_row, textvariable=self.status_var)
        status_label._flow_wrap = True
        status_label.pack(side="left")
        ttk.Label(status_row, textvariable=self.count_var).pack(side="left", padx=(18, 0))
        self.progress = ttk.Progressbar(status_row, mode="determinate", maximum=100, value=0)
        self.progress._flow_expand = True
        self.progress.pack(side="right", fill="x", expand=True, padx=(20,0))
        self.status_var.trace_add("write", lambda *args: status_row._schedule())
        self.count_var.trace_add("write", lambda *args: status_row._schedule())

        workspace = self.workspace = ttk.Panedwindow(self.sections, orient="vertical")
        self.sections.add(workspace, weight=1)
        middle = self.middle = ttk.Panedwindow(workspace, orient="horizontal")
        workspace.add(middle, weight=5)

        list_frame = ttk.LabelFrame(middle, text="Juegos", padding=6)
        detail_frame = ttk.LabelFrame(middle, text="Detalle", padding=10)
        middle.add(list_frame, weight=4)
        middle.add(detail_frame, weight=2)

        columns = ("name", "symbol", "status", "tested", "url", "purchases", "antebets", "mechanics")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Miniatura")
        self.tree.heading("name", text="Nombre")
        self.tree.heading("symbol", text="ID proveedor")
        self.tree.heading("status", text="Estado")
        self.tree.heading("tested", text="Última prueba")
        self.tree.heading("url", text="Link")
        self.tree.heading("purchases", text="Cantidad de compras")
        self.tree.heading("antebets", text="Cantidad de antebets")
        self.tree.column("purchases", width=140, minwidth=45, anchor="center", stretch=False)
        self.tree.column("antebets", width=140, minwidth=45, anchor="center", stretch=False)
        self.tree.heading("mechanics", text="Mecánica particular")
        self.tree.column("mechanics", width=250, minwidth=60, stretch=False)
        self.tree.configure(displaycolumns=("name", "symbol", "status", "purchases", "antebets", "mechanics", "tested", "url"))
        self.tree.column("#0", width=84, minwidth=60, stretch=False)
        self.tree.column("name", width=180, minwidth=130)
        self.tree.column("symbol", width=90, minwidth=60, stretch=False)
        self.tree.column("status", width=80, minwidth=70, anchor="center", stretch=False)
        self.tree.column("tested", width=130, minwidth=100, stretch=False)
        self.tree.column("url", width=250, minwidth=140)
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_game())
        self.tree.bind("<Double-1>", self._on_game_double_click)
        self.tree.bind("<Control-c>", self._copy_selected_game_firefox)
        self.tree.bind("<Control-C>", self._copy_selected_game_firefox)


        self.detail_panes = ttk.Panedwindow(detail_frame, orient="vertical")
        self.detail_panes.pack(fill="both", expand=True)
        preview_frame = ttk.Frame(self.detail_panes)
        self.detail_panes.add(preview_frame, weight=0)
        self.preview_label = ttk.Label(preview_frame, text="Sin miniatura", anchor="center")
        self.preview_label.pack(fill="both", expand=True, pady=(0, 6))
        preview_frame.bind("<Configure>", lambda event: self.after_idle(self._resize_preview), add="+")
        selection_label = self.preview_title = ttk.Label(preview_frame, textvariable=self.selection_var, font=("TkDefaultFont",12,"bold"))
        selection_label.pack(fill="x")
        selection_label.bind("<Configure>", lambda event: selection_label.configure(wraplength=max(60,event.width)))
        detail_body = ttk.Frame(self.detail_panes)
        self.detail_panes.add(detail_body, weight=1)
        self.detail_text = tk.Text(detail_body, height=6, width=36, wrap="word", state="disabled")
        detail_scroll = ttk.Scrollbar(detail_body, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side="right",fill="y")
        self.detail_text.pack(side="left",fill="both",expand=True)
        manual_actions = FlowFrame(self.detail_panes, collapse_at=450, menu_label="Acciones del juego")
        self.detail_panes.add(manual_actions, weight=0)
        ttk.Button(manual_actions, text="Marcar OK manual",
                   command=lambda: self._set_selected_manual_ok(True)).pack(side="left")
        ttk.Button(manual_actions, text="Quitar OK manual",
                   command=lambda: self._set_selected_manual_ok(False)).pack(side="left", padx=(8, 0))
        detail_actions = manual_actions

        ttk.Button(detail_actions, text="Abrir juego", command=self._open_selected_url).pack(side="left")
        self.hardfire_btn = ttk.Button(detail_actions, text="Abrir en HardFire", command=self._open_selected_hardfire)
        self.hardfire_btn.pack(side="left", padx=(8, 0))
        ttk.Button(detail_actions, text="Opciones del juego", command=self._open_manual_controls).pack(side="left", padx=(8, 0))
        ttk.Button(detail_actions, text="Abrir carpeta", command=self._open_selected_folder).pack(side="left", padx=(8, 0))
        ttk.Button(detail_actions, text="Probar este juego", command=self._test_selected).pack(side="left", padx=(8, 0))

        log_frame = ttk.LabelFrame(workspace, text="Registro", padding=6)
        workspace.add(log_frame, weight=1)
        self.log = tk.Text(log_frame, height=4, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

    def _resize_preview(self):
        if self._preview_original is None:
            return
        parent = self.preview_label.master
        size = (max(60,parent.winfo_width()-24), max(24, parent.winfo_height() - self.preview_title.winfo_reqheight() - 12))
        if size == self._preview_size:
            return
        self._preview_size = size
        image = self._preview_original.copy()
        image.thumbnail(size, Image.Resampling.LANCZOS)
        self._preview_image = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self._preview_image,text="")

    def _provider(self):
        key = self._display_to_key[self.provider_var.get()]
        return self.registry.get(key)

    def _on_provider_changed(self) -> None:
        provider = self._provider()
        self.catalog_url_var.set(provider.catalog_url)
        self._refresh_games()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.crawl_btn.configure(state=state)
        self.test_selected_btn.configure(state=state)
        self.test_all_btn.configure(state=state)
        self.provider_combo.configure(state="disabled" if busy else "readonly")
        self.stop_btn.configure(state="normal" if busy else "disabled")

    def _start_crawl(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        try:
            max_pages = max(1, int(self.max_pages_var.get()))
        except ValueError:
            messagebox.showerror("Tester-Spin", "Máx. páginas debe ser un entero.")
            return
        provider = self._provider()
        provider.catalog_url = self.catalog_url_var.get().strip() or provider.catalog_url
        self._stop_event = threading.Event()
        self._set_busy(True)
        self.status_var.set("Cargando catálogo...")
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)

        def worker() -> None:
            try:
                games = provider.crawl_catalog(
                    stop_event=self._stop_event,
                    progress=lambda message: self._events.put(("log", message)),
                    max_pages=max_pages,
                )
                self.storage.upsert_games(games)
                self._events.put(("catalog_done", len(games)))
            except Exception as exc:
                self._events.put(("error", f"Catálogo: {type(exc).__name__}: {exc}"))

        self._worker = threading.Thread(target=worker, daemon=True, name="catalog-crawler")
        self._worker.start()

    def _test_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Tester-Spin", "Seleccioná al menos un juego.")
            return
        games = [self._games[item_id] for item_id in selected if item_id in self._games]
        self._start_tests(games)

    def _test_all(self) -> None:
        games = list(self._games.values())
        if not games:
            messagebox.showinfo("Tester-Spin", "Primero cargá el catálogo.")
            return
        if not messagebox.askyesno("Tester-Spin", f"¿Probar los {len(games)} juegos del proveedor seleccionado?"):
            return
        self._start_tests(games)

    def _start_tests(self, games: list[Game]) -> None:
        if self._worker and self._worker.is_alive():
            return
        try:
            concurrency = max(1, int(self.concurrency_var.get()))
            repetitions = max(1, int(self.spins_var.get()))
            delay_s = max(0.0, float(self.delay_var.get()))
            timeout_s = max(1.0, float(self.timeout_var.get()))
            operation_delay_s = float(self.operation_delay_var.get().replace(",", "."))
            import math
            if not math.isfinite(operation_delay_s) or operation_delay_s < 0:
                raise ValueError("Delay entre operaciones inválido")
        except ValueError:
            messagebox.showerror("Tester-Spin", "Revisá concurrencia, repeticiones, delay y timeout.")
            return

        provider = self._provider()
        if provider.key == "ka_gaming":
            from tester_spin.providers.ka_gaming.limits import REQUEST_GATE
            REQUEST_GATE.configure_delay(operation_delay_s)
        self._stop_event = threading.Event()
        self._test_total = len(games)
        self._test_done = 0
        self._set_busy(True)
        self.status_var.set(f"Probando 0/{len(games)}...")
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=max(1, len(games)), value=0)
        self._append_log(
            f"=== INICIO: proveedor={provider.display_name}, juegos={len(games)}, "
            f"simultáneos={concurrency}, repeticiones/modo={repetitions}, delay={delay_s}s, delay operaciones KA={operation_delay_s}s ==="
        )

        def on_result(result: GameTestResult) -> None:
            self.storage.record_result(result)
            self._events.put(("test_result", result))

        def worker() -> None:
            try:
                run_game_tests(
                    provider,
                    games,
                    concurrency=concurrency,
                    spins_per_game=repetitions,
                    delay_between_starts_s=delay_s,
                    timeout_s=timeout_s,
                    stop_event=self._stop_event,
                    progress=lambda message: self._events.put(("log", message)),
                    on_result=on_result,
                )
                self._events.put(("tests_done", None))
            except Exception as exc:
                self._events.put(("error", f"Pruebas: {type(exc).__name__}: {exc}"))

        self._worker = threading.Thread(target=worker, daemon=True, name="game-test-scheduler")
        self._worker.start()

    def _stop(self) -> None:
        self._stop_event.set()
        self.status_var.set("Deteniendo...")
        self.stop_btn.configure(state="disabled")

    def _refresh_games(self) -> None:
        if not self.provider_var.get() or self.provider_var.get() not in self._display_to_key:
            return
        provider = self._provider()
        games = self.storage.list_games(provider.key)
        self._games.clear()
        # Retain decoded images for this catalogue across refreshes, but release
        # providers no longer displayed. Tk rows keep references through this cache.
        paths = {str(Path(game.thumbnail_path)) for game in games if game.thumbnail_path}
        self._thumb_images = {key: value for key, value in self._thumb_images.items() if key in paths}
        self._thumb_signatures = {key: value for key, value in self._thumb_signatures.items() if key in paths}
        self._thumbnail_generation = getattr(self, "_thumbnail_generation", 0) + 1
        generation = self._thumbnail_generation
        pending = []
        for item in self.tree.get_children():
            self.tree.delete(item)

        for game in games:
            iid = f"{game.provider}::{game.slug}"
            self._games[iid] = game
            image = self._cached_tree_thumbnail(game.thumbnail_path)
            if game.thumbnail_path and not image:
                pending.append((iid, game.thumbnail_path))
            values = (
                game.name,
                game.symbol or "—",
                game.display_status or "PENDIENTE",
                game.last_test_at or "—",
                game.launch_url,
            )
            self.tree.insert("", "end", iid=iid, text="", image=image, values=values)
        self.count_var.set(f"{len(games)} juegos")
        if pending:
            self.after(25, lambda: self._fill_tree_thumbnails(generation, iter(pending)))

    def _fill_tree_thumbnails(self, generation, pending):
        """Decode a bounded batch after the catalogue is already usable."""
        import time
        if generation != self._thumbnail_generation:
            return
        started = time.perf_counter()
        for _ in range(12):
            item = next(pending, None)
            if item is None:
                return
            iid, path = item
            if self.tree.exists(iid):
                self.tree.item(iid, image=self._load_tree_thumbnail(path))
            if time.perf_counter() - started >= 0.008:
                break
        self.after(15, lambda: self._fill_tree_thumbnails(generation, pending))

    def _cached_tree_thumbnail(self, path_text):
        if not path_text:
            return ""
        key = str(Path(path_text))
        if key not in self._thumb_images:
            return ""
        try:
            stat = Path(path_text).stat()
            if self._thumb_signatures.get(key) == (stat.st_mtime_ns, stat.st_size):
                return self._thumb_images[key]
        except OSError:
            pass
        self._thumb_images.pop(key, None)
        self._thumb_signatures.pop(key, None)
        return ""

    def _load_tree_thumbnail(self, path_text: str):
        if not path_text:
            return ""
        path = Path(path_text)
        if not path.exists():
            return ""
        key = str(path)
        cached = self._cached_tree_thumbnail(path_text)
        if cached:
            return cached
        try:
            with Image.open(path) as original:
                image = original.copy()
            image.thumbnail((96, 64), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self._thumb_images[key] = photo
            stat = path.stat()
            self._thumb_signatures[key] = (stat.st_mtime_ns, stat.st_size)
            return photo
        except Exception:
            return ""

    def _set_selected_manual_ok(self, enabled: bool) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("Tester-Spin", "Esperá a que termine la tarea en curso.")
            return
        selection = self.tree.selection()
        if len(selection) != 1:
            messagebox.showinfo("Tester-Spin", "Seleccioná un solo juego para revisar.")
            return
        game = self._games.get(selection[0])
        if game is None:
            return
        note = ""
        if enabled:
            note = simpledialog.askstring(
                "Marcar OK manual",
                f"{game.name}\nNota opcional (por ejemplo: no tiene compras).\n"
                "Aceptar marca este resultado como revisado. Una prueba nueva se evaluará nuevamente.",
                initialvalue=game.manual_ok_note, parent=self)
            if note is None:
                return
        try:
            self.storage.set_manual_ok(game.provider, game.slug, note, enabled=enabled)
        except Exception as exc:
            messagebox.showerror("Tester-Spin", str(exc))
            return
        self._refresh_games()
        self.tree.selection_set(selection[0])
        self._show_selected_game()
        from tester_spin.manual_review import write_review
        try:
            report = write_review(self.storage.latest_results(), self.data_root / "reports")
            self._append_log(f"Lista de revisión actualizada: {report}")
        except Exception as exc:
            self._append_log(f"La marca se guardó; no se pudo actualizar la lista: {exc}")
        self.status_var.set(f"{game.name}: {'OK manual' if enabled else 'marca manual retirada'}")

    def _show_selected_game(self) -> None:
        from tester_spin.feature_summary import feature_summary
        selection = self.tree.selection()
        if not selection:
            self.selection_var.set("Sin selección")
            return
        game = self._games.get(selection[0])
        if game is None:
            return
        self.selection_var.set(game.name)

        result = next((row for row in self.storage.latest_results()
                       if row.get('provider') == game.provider and row.get('slug') == game.slug), {})

        text = (
            f"Proveedor: {game.provider}\n"
            f"ID interno: {game.symbol or 'sin resolver'}\n"
            f"Slug: {game.slug}\n"
            f"Estado: {game.display_status}\n"
            f"{feature_summary(result)}\n"
            f"Resultado automático: {game.last_status}\n"
            f"Revisión manual: {game.manual_ok_at or '—'} {game.manual_ok_note}\n"
            f"Última prueba: {game.last_test_at or '—'}\n"
            f"Error: {game.last_error or '—'}\n\n"
            f"Juego:\n{game.launch_url}\n\n"
            f"Miniatura original:\n{game.thumbnail_url or '—'}\n\n"
            f"Archivo:\n{game.thumbnail_path or '—'}"
        )
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

        self._preview_image = None
        self._preview_original = None
        self._preview_size = None
        if game.thumbnail_path and Path(game.thumbnail_path).exists():
            try:
                with Image.open(game.thumbnail_path) as original:
                    image = original.copy()
                self._preview_original = image.copy()
                self._resize_preview()
                return
            except Exception:
                pass
        self.preview_label.configure(image="", text="Sin miniatura")

    def _on_game_double_click(self,event):
        if self.tree.identify_region(event.x,event.y) not in ('tree','cell'):return
        iid=self.tree.identify_row(event.y)
        if iid not in self._games:return
        self.tree.selection_set(iid);self.tree.focus(iid)
        self._open_selected_hardfire()
        return 'break'

    def _open_selected_hardfire(self):
        selection=self.tree.selection()
        game=self._games.get(selection[0]) if selection else None
        if game is None or self._hardfire_opening:return
        self._hardfire_opening=True
        self.hardfire_btn.configure(state='disabled')
        url,name=game.launch_url,game.name
        self._append_log('Abriendo en HardFire: '+name)
        def launch():
            try:
                from tester_spin.hardfire_launcher import HardFireClient
                HardFireClient().open_game(url)
                self._events.put(('hardfire_opened',name))
            except Exception as exc:
                self._events.put(('hardfire_error',str(exc)))
        threading.Thread(target=launch,daemon=True,name='open-hardfire').start()

    def _open_manual_controls(self):
        existing=getattr(self,"_manual_controls_dialog",None)
        if existing is not None and existing.winfo_exists():existing.lift();return
        from tester_spin.manual_controls_ui import ManualControlsDialog
        self._manual_controls_dialog=ManualControlsDialog(self,self.data_root)

    def _finish_hardfire_open(self,kind,value):
        self._hardfire_opening=False
        self.hardfire_btn.configure(state='normal')
        if kind=='hardfire_error':
            messagebox.showerror('HardFire',str(value),parent=self)
            return 'No pude abrir HardFire: '+str(value)
        return 'Juego abierto en HardFire: '+str(value)

    def _copy_selected_game_firefox(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return "break"
        focused = self.tree.focus()
        game = self._games.get(focused if focused in selection else selection[0])
        if game is None or not game.launch_url:
            return "break"
        url = game.launch_url
        self.clipboard_clear()
        self.clipboard_append(url)
        try:
            open_firefox(url)
        except (OSError, ValueError) as exc:
            self.status_var.set(f"Enlace copiado. No pude abrir Firefox: {exc}")
        else:
            self.status_var.set(f"Enlace copiado y abierto en Firefox: {game.name}")
        return "break"

    def _open_selected_url(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        game = self._games.get(selection[0])
        if game:
            webbrowser.open(game.launch_url)

    def _open_selected_folder(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        game = self._games.get(selection[0])
        if not game:
            return
        provider = self._provider()
        path = provider.game_dir(game) if hasattr(provider, "game_dir") else self.data_root
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _drain_events(self) -> None:
        while True:
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                break

            if kind in ("hardfire_opened", "hardfire_error"):
                self._append_log(self._finish_hardfire_open(kind,value))
            elif kind == "log":
                self._append_log(str(value))
            elif kind == "catalog_done":
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=100, value=100)
                self._set_busy(False)
                self.status_var.set(f"Catálogo actualizado: {value} juegos")
                self._refresh_games()
            elif kind == "test_result":
                result = value
                if isinstance(result, GameTestResult):
                    self._test_done += 1
                    self.progress.configure(value=self._test_done)
                    self.status_var.set(f"Probando {self._test_done}/{self._test_total}...")
                    warning_count = sum(1 for attempt in result.attempts if attempt.warning)
                    self._append_log(
                        f"[{result.game_name}] {result.status}: "
                        f"{result.successful_spins}/{result.requested_spins} intentos de modo OK"
                        + (f", warnings={warning_count}" if warning_count else "")
                    )
                    self._refresh_games()
            elif kind == "tests_done":
                self._set_busy(False)
                self.status_var.set(f"Pruebas terminadas: {self._test_done}/{self._test_total}")
                self.progress.configure(value=self._test_total)
                self._refresh_games()
            elif kind == "error":
                self.progress.stop()
                self._set_busy(False)
                self.status_var.set("Error")
                self._append_log(str(value))
                messagebox.showerror("Tester-Spin", str(value))

        self.after(100, self._drain_events)

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> None:
    TesterSpinApp().mainloop()


if __name__ == "__main__":
    main()
