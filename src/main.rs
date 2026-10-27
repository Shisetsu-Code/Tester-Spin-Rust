#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod engine;
use eframe::egui::{self, Align, Color32, Layout, RichText, TextureHandle};
use egui_extras::{Column, TableBuilder};
use serde_json::{Value, json};
use std::collections::{BTreeSet, VecDeque};
use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, Sender};
use tester_spin_rust::{
    Config, Details, Game, load_details, load_games, open_firefox, project_root, visible_indices,
};

enum UiEvent {
    Loaded(Vec<Game>, f64),
    Details(String, Details),
    Preview(String, egui::ColorImage),
    Error(String),
    Log(String),
    Engine(Value),
    EngineExited(bool),
}

struct App {
    config: Config,
    sender: Sender<UiEvent>,
    receiver: Receiver<UiEvent>,
    games: Vec<Game>,
    visible: Vec<usize>,
    providers: Vec<String>,
    provider: String,
    status_filter: String,
    search: String,
    sort: String,
    reverse: bool,
    selected: BTreeSet<String>,
    active: Option<usize>,
    details: Option<Details>,
    preview: Option<TextureHandle>,
    loading: bool,
    running: bool,
    status: String,
    load_ms: f64,
    logs: VecDeque<String>,
    engine: Option<engine::Engine>,
    spins: u32,
    concurrency: u32,
    timeout: u32,
    delay: f64,
    done: u64,
    total: u64,
    screenshot: Option<PathBuf>,
    frames: usize,
    close_when_done: bool,
}

impl App {
    fn new(cc: &eframe::CreationContext<'_>, config: Config, screenshot: Option<PathBuf>) -> Self {
        cc.egui_ctx.set_theme(egui::Theme::Dark);
        cc.egui_ctx.global_style_mut(|style| {
            style.spacing.item_spacing = egui::vec2(10.0, 8.0);
            style.spacing.button_padding = egui::vec2(12.0, 8.0);
            style.visuals.selection.bg_fill = Color32::from_rgb(40, 80, 110);
        });
        let (sender, receiver) = mpsc::channel();
        let mut app = Self {
            config,
            sender,
            receiver,
            games: Vec::new(),
            visible: Vec::new(),
            providers: Vec::new(),
            provider: String::new(),
            status_filter: String::new(),
            search: String::new(),
            sort: "name".into(),
            reverse: false,
            selected: BTreeSet::new(),
            active: None,
            details: None,
            preview: None,
            loading: false,
            running: false,
            status: "Cargando catálogo local…".into(),
            load_ms: 0.0,
            logs: VecDeque::new(),
            engine: None,
            spins: 1,
            concurrency: 1,
            timeout: 30,
            delay: 1.0,
            done: 0,
            total: 0,
            screenshot,
            frames: 0,
            close_when_done: false,
        };
        app.reload(&cc.egui_ctx);
        app
    }
    fn log(&mut self, message: String) {
        if self.logs.back() != Some(&message) {
            self.logs.push_back(message);
        }
        while self.logs.len() > 300 {
            self.logs.pop_front();
        }
    }
    fn reload(&mut self, ctx: &egui::Context) {
        if self.loading {
            return;
        }
        self.loading = true;
        let path = self.config.database();
        let tx = self.sender.clone();
        let ctx = ctx.clone();
        std::thread::spawn(move || {
            let event = match load_games(&path) {
                Ok((games, ms)) => UiEvent::Loaded(games, ms),
                Err(e) => UiEvent::Error(e.to_string()),
            };
            let _ = tx.send(event);
            ctx.request_repaint();
        });
    }
    fn filter(&mut self) {
        self.visible = visible_indices(
            &self.games,
            &self.provider,
            &self.status_filter,
            &self.search,
        );
        let field = self.sort.as_str();
        let games = &self.games;
        self.visible.sort_by(|&a, &b| {
            let value = |game: &Game| match field {
                "provider" => game.provider.clone(),
                "status" => game.status.clone(),
                "tested" => game.tested.clone(),
                _ => game.name.to_lowercase(),
            };
            let order = value(&games[a])
                .cmp(&value(&games[b]))
                .then(games[a].name.cmp(&games[b].name));
            if self.reverse { order.reverse() } else { order }
        });
    }
    fn select(&mut self, index: usize, keep: bool, ctx: &egui::Context) {
        if !keep {
            self.selected.clear();
        }
        self.selected.insert(self.games[index].key());
        self.active = Some(index);
        self.details = None;
        self.preview = None;
        let game = self.games[index].clone();
        let config = self.config.clone();
        let tx = self.sender.clone();
        let ctx = ctx.clone();
        std::thread::spawn(move || {
            match load_details(&config.database(), &game) {
                Ok(details) => {
                    let _ = tx.send(UiEvent::Details(game.key(), details));
                }
                Err(e) => {
                    let _ = tx.send(UiEvent::Details(
                        game.key(),
                        Details {
                            error: format!("No se pudo leer el detalle: {e}"),
                            ..Default::default()
                        },
                    ));
                }
            }
            if !game.thumbnail.is_empty() {
                let source = PathBuf::from(&game.thumbnail);
                let path = if source.is_absolute() {
                    source
                } else {
                    let local = config.root.join(&source);
                    if local.is_file() {
                        local
                    } else {
                        config
                            .source_data
                            .parent()
                            .unwrap_or(&config.source_data)
                            .join(source)
                    }
                };
                if let Ok(image) = image::open(&path) {
                    let image = image.thumbnail(310, 165).into_rgba8();
                    let pixels = egui::ColorImage::from_rgba_unmultiplied(
                        [image.width() as usize, image.height() as usize],
                        image.as_raw(),
                    );
                    let _ = tx.send(UiEvent::Preview(game.key(), pixels));
                }
            }
            ctx.request_repaint();
        });
    }
    fn launch_active(&mut self, ctx: &egui::Context, copy: bool) {
        if let Some(index) = self.active {
            let game = &self.games[index];
            if copy {
                ctx.copy_text(game.launch_url());
            }
            self.status = match open_firefox(game) {
                Ok(()) => format!(
                    "{}{}",
                    if copy {
                        "Enlace copiado · Firefox: "
                    } else {
                        "Firefox: "
                    },
                    game.name
                ),
                Err(e) => format!("{}{}", if copy { "Enlace copiado · " } else { "" }, e),
            };
        }
    }
    fn start(&mut self, ctx: &egui::Context, catalog: bool, dry_run: bool) {
        if self.running {
            return;
        }
        let games: Vec<_> = self
            .games
            .iter()
            .filter(|g| self.selected.contains(&g.key()))
            .collect();
        let provider = if catalog {
            self.provider.clone()
        } else {
            games
                .first()
                .map(|g| g.provider.clone())
                .unwrap_or_default()
        };
        if provider.is_empty() {
            self.status = "Seleccioná un proveedor o un juego".into();
            return;
        }
        if !catalog && games.iter().any(|g| g.provider != provider) {
            self.status = "Seleccioná juegos de un mismo proveedor para esta tanda".into();
            return;
        }
        let slugs: Vec<_> = games.iter().map(|g| g.slug.clone()).collect();
        if !catalog && slugs.is_empty() {
            self.status = "Seleccioná al menos un juego".into();
            return;
        }
        if self.engine.is_none() {
            match engine::Engine::start(&self.config, self.sender.clone(), ctx.clone()) {
                Ok(engine) => self.engine = Some(engine),
                Err(error) => {
                    self.status = error;
                    return;
                }
            }
        }
        let request = json!({"cmd":if catalog { "catalog" } else { "run" },"provider":provider,"slugs":slugs,
            "spins":self.spins,"concurrency":self.concurrency,"timeout":self.timeout,"delay":self.delay,"dry_run":dry_run});
        match self.engine.as_ref().unwrap().send(request) {
            Ok(()) => {
                self.running = true;
                self.done = 0;
                self.total = slugs.len() as u64;
                self.status = if catalog {
                    "Actualizando catálogo…"
                } else if dry_run {
                    "Comprobando selección sin ejecutar juegos…"
                } else {
                    "Preparando pruebas…"
                }
                .into();
            }
            Err(error) => self.status = error,
        }
    }
    fn events(&mut self, ctx: &egui::Context) {
        let mut processed = 0;
        for _ in 0..128 {
            let Ok(event) = self.receiver.try_recv() else {
                break;
            };
            processed += 1;
            match event {
                UiEvent::Loaded(games, ms) => {
                    let active_key = self.active.map(|i| self.games[i].key());
                    self.games = games;
                    self.load_ms = ms;
                    self.loading = false;
                    self.providers = self
                        .games
                        .iter()
                        .map(|g| g.provider.clone())
                        .chain(self.config.provider_names.keys().cloned())
                        .collect::<BTreeSet<_>>()
                        .into_iter()
                        .collect();
                    self.active =
                        active_key.and_then(|key| self.games.iter().position(|g| g.key() == key));
                    self.filter();
                    self.status = format!("Listo · {} juegos", self.games.len());
                }
                UiEvent::Details(key, details) => {
                    if self.active.is_some_and(|i| self.games[i].key() == key) {
                        self.details = Some(details);
                    }
                }
                UiEvent::Preview(key, image) => {
                    if self.active.is_some_and(|i| self.games[i].key() == key) {
                        self.preview =
                            Some(ctx.load_texture(key, image, egui::TextureOptions::LINEAR));
                    }
                }
                UiEvent::Error(message) => {
                    self.loading = false;
                    self.status = message.clone();
                    self.log(message);
                }
                UiEvent::Log(message) => self.log(message),
                UiEvent::EngineExited(ok) => {
                    if self.running {
                        self.status = "El motor se cerró; revisá los registros".into();
                        self.running = false;
                    }
                    if !ok {
                        self.log("El motor terminó con un error".into());
                    }
                    self.engine = None;
                    if self.close_when_done {
                        ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                    }
                }
                UiEvent::Engine(value) => match value["event"].as_str().unwrap_or("") {
                    "ready" => self.log("Motor local preparado".into()),
                    "log" => self.log(value["text"].as_str().unwrap_or("").to_owned()),
                    "error" => {
                        self.status = value["message"]
                            .as_str()
                            .unwrap_or("Error de ejecución")
                            .into();
                        self.log(self.status.clone());
                    }
                    "started" => {
                        self.total = value["total"].as_u64().unwrap_or(0);
                        self.status = format!("Probando 0/{}…", self.total);
                    }
                    "result" => {
                        self.done = value["done"].as_u64().unwrap_or(self.done);
                        let key = format!(
                            "{}::{}",
                            value["provider"].as_str().unwrap_or(""),
                            value["slug"].as_str().unwrap_or("")
                        );
                        if let Some(game) = self.games.iter_mut().find(|g| g.key() == key) {
                            game.status = value["status"].as_str().unwrap_or("PARCIAL").into();
                            game.tested = value["tested"].as_str().unwrap_or("").into();
                            game.error = value["error"].as_str().unwrap_or("").into();
                            if let Some(symbol) = value["symbol"].as_str().filter(|s| !s.is_empty())
                            {
                                game.symbol = symbol.into();
                            }
                            game.search_text = format!(
                                "{} {} {} {}",
                                game.name, game.symbol, game.slug, game.provider
                            )
                            .to_lowercase();
                        }
                        self.status = format!("Probando {}/{}…", self.done, self.total);
                        self.log(format!(
                            "{} · {}",
                            key,
                            value["status"].as_str().unwrap_or("")
                        ));
                        self.filter();
                        if self.active.is_some_and(|i| self.games[i].key() == key) {
                            self.select(self.active.unwrap(), true, ctx);
                        }
                    }
                    "plan" => self.log(format!(
                        "Selección comprobada: {} juegos; ninguna operación ejecutada",
                        value["games"].as_array().map_or(0, Vec::len)
                    )),
                    "done" => {
                        self.running = false;
                        self.status = if value["failed"].as_bool() == Some(true) {
                            "La operación terminó con errores".into()
                        } else if value["cancelled"].as_bool() == Some(true) {
                            "Detenido; evidencias conservadas".into()
                        } else {
                            "Operación terminada".into()
                        };
                        if value["operation"] == "catalog" {
                            self.reload(ctx);
                        }
                        if self.close_when_done {
                            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                        }
                    }
                    _ => {}
                },
            }
        }
        if processed == 128 {
            ctx.request_repaint();
        }
    }
    fn table(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        let mut clicked = None;
        let mut sort = None;
        let height = ui.available_height();
        TableBuilder::new(ui)
            .striped(true)
            .resizable(true)
            .max_scroll_height(height)
            .cell_layout(Layout::left_to_right(Align::Center))
            .column(Column::exact(25.0))
            .column(Column::remainder().at_least(150.0))
            .column(Column::initial(105.0))
            .column(Column::initial(100.0))
            .column(Column::initial(120.0))
            .header(28.0, |mut header| {
                header.col(|ui| {
                    ui.label("");
                });
                for (key, label) in [
                    ("name", "Juego"),
                    ("provider", "Proveedor"),
                    ("status", "Estado"),
                    ("tested", "Última prueba"),
                ] {
                    header.col(|ui| {
                        if ui.small_button(label).clicked() {
                            sort = Some(key.to_owned());
                        }
                    });
                }
            })
            .body(|body| {
                body.rows(36.0, self.visible.len(), |mut row| {
                    let index = self.visible[row.index()];
                    let game = &self.games[index];
                    let key = game.key();
                    row.set_selected(self.active == Some(index));
                    row.col(|ui| {
                        let mut checked = self.selected.contains(&key);
                        if ui.checkbox(&mut checked, "").changed() {
                            if checked {
                                self.selected.insert(key.clone());
                            } else {
                                self.selected.remove(&key);
                            }
                        }
                    });
                    row.col(|ui| {
                        if ui
                            .selectable_label(self.active == Some(index), &game.name)
                            .on_hover_text(&game.symbol)
                            .clicked()
                        {
                            clicked = Some(index);
                        }
                    });
                    row.col(|ui| {
                        ui.label(
                            self.config
                                .provider_names
                                .get(&game.provider)
                                .unwrap_or(&game.provider),
                        );
                    });
                    row.col(|ui| {
                        let color = match game.status.as_str() {
                            "OK" | "OK MANUAL" => Color32::from_rgb(105, 210, 155),
                            "PARCIAL" => Color32::from_rgb(235, 185, 95),
                            "ERROR" => Color32::from_rgb(240, 125, 125),
                            _ => Color32::GRAY,
                        };
                        ui.colored_label(color, &game.status);
                    });
                    row.col(|ui| {
                        ui.small(game.tested.get(..16).unwrap_or(&game.tested));
                    });
                });
            });
        if let Some(index) = clicked {
            self.select(index, ctx.input(|i| i.modifiers.ctrl), ctx);
        }
        if let Some(sort) = sort {
            if self.sort == sort {
                self.reverse = !self.reverse;
            } else {
                self.sort = sort;
                self.reverse = false;
            }
            self.filter();
        }
    }
    fn detail_panel(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        let Some(index) = self.active else {
            ui.heading("Detalle del juego");
            ui.label("Elegí un juego para ver su resultado y sus modos.");
            return;
        };
        let game = self.games[index].clone();
        ui.heading(&game.name);
        ui.label(format!("{} · {}", game.provider, game.symbol));
        if let Some(texture) = &self.preview {
            ui.image((texture.id(), texture.size_vec2()));
        }
        ui.horizontal_wrapped(|ui| {
            if ui.button("Abrir Firefox").clicked() {
                self.launch_active(ctx, false);
            }
            if ui.button("Copiar enlace").clicked() {
                ctx.copy_text(game.launch_url());
                self.status = "Enlace copiado".into();
            }
        });
        ui.small("Ctrl+C: copiar enlace y abrir en Firefox");
        ui.separator();
        ui.label(RichText::new(&game.status).strong());
        if !game.error.is_empty() {
            ui.colored_label(Color32::from_rgb(240, 150, 150), &game.error);
        }
        if let Some(details) = &self.details {
            if !details.error.is_empty() && details.error != game.error {
                ui.colored_label(Color32::from_rgb(240, 150, 150), &details.error);
            }
            ui.label(format!(
                "Tiradas: {} correctas · {} fallidas / {}",
                details.success, details.failed, details.requested
            ));
            if let Some(ms) = details.elapsed_ms {
                ui.small(format!("Tiempo de prueba: {:.1} s", ms / 1000.0));
            }
            ui.separator();
            ui.strong(format!("Modos registrados ({})", details.modes.len()));
            egui::ScrollArea::vertical()
                .id_salt("modes")
                .max_height(200.0)
                .show(ui, |ui| {
                    for (label, kind) in &details.modes {
                        ui.label(label);
                        ui.small(kind);
                        ui.add_space(4.0);
                    }
                    if details.modes.is_empty() {
                        ui.small("Sin modos registrados todavía");
                    }
                });
        } else {
            ui.small("Leyendo último resultado…");
        }
    }
}

impl eframe::App for App {
    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.events(ctx);
    }
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        self.frames += 1;
        if !ctx.text_edit_focused()
            && ctx.input(|i| i.events.iter().any(|e| matches!(e, egui::Event::Copy)))
        {
            self.launch_active(&ctx, true);
        }
        egui::CentralPanel::default().show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new("Tester Spin").size(27.0).strong());
                ui.add_space(12.0);
                ui.label("Catálogo y pruebas");
                ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                    ui.small(format!(
                        "{} juegos · carga {:.0} ms",
                        self.games.len(),
                        self.load_ms
                    ));
                });
            });
            ui.add_space(8.0);
            ui.horizontal_wrapped(|ui| {
                let mut changed = ui
                    .add(
                        egui::TextEdit::singleline(&mut self.search)
                            .hint_text("Buscar juego o ID…")
                            .desired_width(250.0),
                    )
                    .changed();
                egui::ComboBox::from_id_salt("provider")
                    .selected_text(if self.provider.is_empty() {
                        "Todos los proveedores"
                    } else {
                        self.config
                            .provider_names
                            .get(&self.provider)
                            .unwrap_or(&self.provider)
                    })
                    .show_ui(ui, |ui| {
                        changed |= ui
                            .selectable_value(
                                &mut self.provider,
                                String::new(),
                                "Todos los proveedores",
                            )
                            .changed();
                        for provider in &self.providers {
                            changed |= ui
                                .selectable_value(
                                    &mut self.provider,
                                    provider.clone(),
                                    self.config.provider_names.get(provider).unwrap_or(provider),
                                )
                                .changed();
                        }
                    });
                egui::ComboBox::from_id_salt("status")
                    .selected_text(if self.status_filter.is_empty() {
                        "Todos los estados"
                    } else {
                        &self.status_filter
                    })
                    .show_ui(ui, |ui| {
                        changed |= ui
                            .selectable_value(
                                &mut self.status_filter,
                                String::new(),
                                "Todos los estados",
                            )
                            .changed();
                        for status in [
                            "PENDIENTE",
                            "OK",
                            "OK MANUAL",
                            "PARCIAL",
                            "ERROR",
                            "SIN_DEMO",
                            "CANCELADO",
                        ] {
                            changed |= ui
                                .selectable_value(&mut self.status_filter, status.into(), status)
                                .changed();
                        }
                    });
                if changed {
                    self.filter();
                }
                if ui
                    .add_enabled(!self.loading, egui::Button::new("Actualizar vista"))
                    .clicked()
                {
                    self.reload(&ctx);
                }
            });
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(
                        !self.running && !self.selected.is_empty(),
                        egui::Button::new("Probar selección"),
                    )
                    .clicked()
                {
                    self.start(&ctx, false, false);
                }
                if ui
                    .add_enabled(
                        !self.running && !self.selected.is_empty(),
                        egui::Button::new("Comprobar selección"),
                    )
                    .on_hover_text("Comprueba el motor sin iniciar juegos")
                    .clicked()
                {
                    self.start(&ctx, false, true);
                }
                if ui
                    .add_enabled(
                        !self.running && !self.provider.is_empty(),
                        egui::Button::new("Actualizar catálogo"),
                    )
                    .clicked()
                {
                    self.start(&ctx, true, false);
                }
                if ui
                    .add_enabled(self.running, egui::Button::new("Detener"))
                    .clicked()
                {
                    if let Some(engine) = &self.engine {
                        let _ = engine.send(json!({"cmd":"stop"}));
                        self.status = "Deteniendo después de la operación en curso…".into();
                    }
                }
                if ui.button("Seleccionar visibles").clicked() {
                    self.selected
                        .extend(self.visible.iter().map(|&i| self.games[i].key()));
                }
                if ui.button("Limpiar selección").clicked() {
                    self.selected.clear();
                }
                ui.small(format!(
                    "{} visibles · {} seleccionados",
                    self.visible.len(),
                    self.selected.len()
                ));
            });
            ui.horizontal(|ui| {
                ui.small("Tiradas");
                ui.add(egui::DragValue::new(&mut self.spins).range(1..=100));
                ui.small("Paralelos");
                ui.add(egui::DragValue::new(&mut self.concurrency).range(1..=16));
                ui.small("Espera de red (s)");
                ui.add(egui::DragValue::new(&mut self.timeout).range(1..=300));
                ui.small("Pausa entre juegos (s)");
                ui.add(
                    egui::DragValue::new(&mut self.delay)
                        .range(0.0..=60.0)
                        .speed(0.1),
                );
            });
            ui.separator();
            let height = (ui.available_height() - 115.0).max(230.0);
            let table_width = (ui.available_width() - 330.0).max(400.0);
            ui.horizontal_top(|ui| {
                ui.allocate_ui_with_layout(
                    egui::vec2(table_width, height),
                    Layout::top_down(Align::Min),
                    |ui| {
                        self.table(ui, &ctx);
                    },
                );
                ui.add_sized([1.0, height], egui::Separator::default().vertical());
                ui.allocate_ui_with_layout(
                    egui::vec2(310.0, height),
                    Layout::top_down(Align::Min),
                    |ui| {
                        self.detail_panel(ui, &ctx);
                    },
                );
            });
            ui.separator();
            ui.horizontal(|ui| {
                ui.label(&self.status);
                if self.running && self.total > 0 {
                    ui.add(
                        egui::ProgressBar::new(self.done as f32 / self.total as f32)
                            .desired_width(170.0)
                            .show_percentage(),
                    );
                }
                if self.loading {
                    ui.small("Leyendo SQLite…");
                }
            });
            egui::ScrollArea::vertical()
                .id_salt("logs")
                .max_height(65.0)
                .stick_to_bottom(true)
                .show(ui, |ui| {
                    for message in &self.logs {
                        ui.small(message);
                    }
                });
        });
        if ctx.input(|i| i.viewport().close_requested()) && self.running {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            self.close_when_done = true;
            if let Some(engine) = &self.engine {
                let _ = engine.send(json!({"cmd":"stop"}));
            }
            self.status = "Deteniendo la operación en curso antes de cerrar…".into();
        }
        if self.screenshot.is_some() && !self.loading {
            if self.frames < 4 {
                ctx.request_repaint();
            } else {
                let target = self.screenshot.take().unwrap();
                let ctx = ctx.clone();
                ctx.clone().request_screenshot(move |image| {
                    let bytes: Vec<u8> = image.pixels.iter().flat_map(|p| p.to_array()).collect();
                    if let Some(parent) = target.parent() {
                        let _ = std::fs::create_dir_all(parent);
                    }
                    let _ = image::save_buffer(
                        &target,
                        &bytes,
                        image.width() as u32,
                        image.height() as u32,
                        image::ColorType::Rgba8,
                    );
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                });
            }
        }
    }
}

fn main() -> eframe::Result {
    let root = project_root().expect("No se encontró el proyecto Tester-Spin-Rust");
    let config = Config::load(&root).expect("No se pudo leer config.json");
    let args: Vec<_> = std::env::args().collect();
    if args.iter().any(|a| a == "--check-data") {
        match load_games(&config.database()) {
            Ok((games, ms)) => println!(
                "{}",
                json!({"games":games.len(),"load_ms":ms,"database":config.database(),"readonly":true})
            ),
            Err(error) => {
                eprintln!("{error}");
                std::process::exit(1);
            }
        }
        return Ok(());
    }
    let screenshot = args
        .iter()
        .position(|a| a == "--screenshot")
        .and_then(|i| args.get(i + 1))
        .map(PathBuf::from);
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Tester Spin · Rust")
            .with_inner_size([1360.0, 860.0])
            .with_min_inner_size([1000.0, 650.0]),
        ..Default::default()
    };
    eframe::run_native(
        "Tester Spin Rust",
        options,
        Box::new(move |cc| Ok(Box::new(App::new(cc, config, screenshot)))),
    )
}

#[cfg(test)]
mod integration {
    use super::*;
    #[test]
    fn native_client_starts_engine_and_checks_selection_without_playing() {
        // The integration contract must work on a fresh checkout: no developer
        // database, machine-specific Python path or previously crawled catalogue.
        struct Project(std::path::PathBuf);
        impl Drop for Project {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
        fn copy_engine(source: &std::path::Path, target: &std::path::Path) {
            std::fs::create_dir_all(target).unwrap();
            for entry in std::fs::read_dir(source).unwrap() {
                let entry = entry.unwrap();
                if entry.file_name() == "__pycache__" {
                    continue;
                }
                let destination = target.join(entry.file_name());
                if entry.file_type().unwrap().is_dir() {
                    copy_engine(&entry.path(), &destination);
                } else if entry.path().extension().is_none_or(|ext| ext != "pyc") {
                    std::fs::copy(entry.path(), destination).unwrap();
                }
            }
        }
        let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let project = Project(std::env::temp_dir().join(format!(
            "tester-spin-integration-{}-{unique}",
            std::process::id()
        )));
        copy_engine(&manifest.join("engine"), &project.0.join("engine"));
        let python = std::env::var_os("TESTER_SPIN_TEST_PYTHON")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(if cfg!(windows) { "python" } else { "python3" }));
        let config_json = json!({
            "python": python,
            "source_data": project.0.join("unused-source"),
            "data_dir": "data",
            "engine_dir": "engine"
        });
        std::fs::write(
            project.0.join("config.json"),
            serde_json::to_vec(&config_json).unwrap(),
        ).unwrap();
        let config = Config::load(&project.0).unwrap();
        let seed = std::process::Command::new(&config.python)
            .args(["-c", "from pathlib import Path; from tester_spin.storage import Storage; from tester_spin.models import Game; store=Storage(Path('data/tester-spin.sqlite3')); store.upsert_games([Game('elk','synthetic-integration','Synthetic integration fixture','https://example.invalid/demo')])"])
            .current_dir(&project.0)
            .env("PYTHONPATH", config.engine_root())
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .output()
            .expect("Python with requirements-ci.txt is required for the bridge integration test");
        assert!(seed.status.success(), "Unable to seed isolated SQLite: {}", String::from_utf8_lossy(&seed.stderr));
        let (games, _) = load_games(&config.database()).unwrap();
        assert_eq!(games.len(), 1);
        let game = games.iter().find(|game| game.provider == "elk").unwrap();
        let (tx, rx) = mpsc::channel();
        let engine = engine::Engine::start(&config, tx, egui::Context::default()).unwrap();
        engine
            .send(json!({"cmd":"run","provider":game.provider,"slugs":[game.slug],"dry_run":true}))
            .unwrap();
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
        let mut planned = false;
        let mut ready = false;
        loop {
            assert!(
                std::time::Instant::now() < deadline,
                "engine did not respond"
            );
            match rx.recv_timeout(std::time::Duration::from_secs(5)).unwrap() {
                UiEvent::Engine(value) if value["event"] == "ready" => ready = true,
                UiEvent::Engine(value) if value["event"] == "plan" => {
                    assert_eq!(value["executed"], false);
                    planned = true;
                }
                UiEvent::Engine(value) if value["event"] == "error" => {
                    panic!("{}", value["message"])
                }
                UiEvent::Engine(value) if value["event"] == "result" => {
                    panic!("dry run executed a game: {value}")
                }
                UiEvent::Engine(value) if value["event"] == "done" => {
                    assert_eq!(value["dry_run"], true);
                    break;
                }
                _ => {}
            }
        }
        assert!(planned && ready);
        let database = rusqlite::Connection::open_with_flags(
            config.database(), rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY
        ).unwrap();
        let result_count: i64 = database.query_row("SELECT COUNT(*) FROM test_results", [], |row| row.get(0)).unwrap();
        assert_eq!(result_count, 0, "dry run must not create gameplay results");
        drop(database);
        engine.send(json!({"cmd":"shutdown"})).unwrap();
        loop {
            if let UiEvent::EngineExited(ok) =
                rx.recv_timeout(std::time::Duration::from_secs(5)).unwrap()
            {
                assert!(ok);
                break;
            }
        }
    }
}
