use crate::{Config, UiEvent};
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Sender};

pub struct Engine {
    sender: Sender<Value>,
}

impl Engine {
    pub fn start(
        config: &Config,
        ui: Sender<UiEvent>,
        ctx: eframe::egui::Context,
    ) -> Result<Self, String> {
        let mut command = Command::new(&config.python);
        command
            .arg("-u")
            .arg(config.engine_root().join("bridge.py"))
            .current_dir(&config.root)
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("PYTHONUTF8", "1")
            .env("PYTHONPATH", config.engine_root())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let mut child = command
            .spawn()
            .map_err(|error| format!("No pude iniciar Python: {error}"))?;
        let mut stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        let (sender, receiver) = mpsc::channel::<Value>();
        let reader_ui = ui.clone();
        let reader_ctx = ctx.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let event = serde_json::from_str(&line)
                    .unwrap_or_else(|_| serde_json::json!({"event":"log","text":line}));
                if reader_ui.send(UiEvent::Engine(event)).is_err() {
                    break;
                }
                reader_ctx.request_repaint();
            }
            let status = child.wait();
            let _ = reader_ui.send(UiEvent::EngineExited(
                status.map(|s| s.success()).unwrap_or(false),
            ));
            reader_ctx.request_repaint();
        });
        let errors = ui.clone();
        let errors_ctx = ctx.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                let _ = errors.send(UiEvent::Log(line));
                errors_ctx.request_repaint();
            }
        });
        std::thread::spawn(move || {
            for request in receiver {
                if writeln!(stdin, "{request}")
                    .and_then(|_| stdin.flush())
                    .is_err()
                {
                    let _ = ui.send(UiEvent::Log("Se cerró la conexión con el motor".into()));
                    ctx.request_repaint();
                    break;
                }
            }
        });
        Ok(Self { sender })
    }
    pub fn send(&self, request: Value) -> Result<(), String> {
        self.sender
            .send(request)
            .map_err(|_| "El motor no está disponible".into())
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        let _ = self.sender.send(serde_json::json!({"cmd":"stop"}));
        let _ = self.sender.send(serde_json::json!({"cmd":"shutdown"}));
    }
}
