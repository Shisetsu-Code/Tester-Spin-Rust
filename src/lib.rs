use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::path::{Component, Path, PathBuf};
use std::time::Instant;

pub type AppResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Clone, Deserialize)]
pub struct Config {
    pub python: PathBuf,
    pub source_data: PathBuf,
    pub data_dir: PathBuf,
    pub engine_dir: PathBuf,
    #[serde(default)]
    pub provider_names: std::collections::BTreeMap<String, String>,
    #[serde(skip)]
    pub root: PathBuf,
}

impl Config {
    pub fn load(root: &Path) -> AppResult<Self> {
        let mut config: Self = serde_json::from_slice(&std::fs::read(root.join("config.json"))?)?;
        for value in [&config.data_dir, &config.engine_dir] {
            if value.is_absolute()
                || value
                    .components()
                    .any(|c| matches!(c, Component::ParentDir))
            {
                return Err(
                    "Los directorios de trabajo deben quedar dentro del proyecto nuevo".into(),
                );
            }
        }
        config.root = root.canonicalize()?;
        Ok(config)
    }
    pub fn data_root(&self) -> PathBuf {
        self.root.join(&self.data_dir)
    }
    pub fn database(&self) -> PathBuf {
        self.data_root().join("tester-spin.sqlite3")
    }
    pub fn engine_root(&self) -> PathBuf {
        self.root.join(&self.engine_dir)
    }
}

pub fn project_root() -> AppResult<PathBuf> {
    let executable = std::env::current_exe()?;
    for base in [
        std::env::current_dir()?,
        executable.parent().unwrap().to_path_buf(),
    ] {
        for path in base.ancestors() {
            if path.join("config.json").is_file() && path.join("engine/bridge.py").is_file() {
                return Ok(path.to_path_buf());
            }
        }
    }
    Err("No se encontró config.json junto al proyecto Tester-Spin-Rust".into())
}

#[derive(Clone, Debug, Serialize)]
pub struct Game {
    pub provider: String,
    pub slug: String,
    pub name: String,
    pub url: String,
    pub symbol: String,
    pub status: String,
    pub tested: String,
    pub error: String,
    pub thumbnail: String,
    #[serde(skip)]
    pub search_text: String,
}

impl Game {
    pub fn key(&self) -> String {
        format!("{}::{}", self.provider, self.slug)
    }
    pub fn launch_url(&self) -> String {
        if self.provider == "playtech" {
            let code = if self.symbol.is_empty() {
                self.slug.strip_prefix("game-").unwrap_or("")
            } else {
                &self.symbol
            };
            if !code.is_empty() {
                let query = url::form_urlencoded::Serializer::new(String::new())
                    .append_pair("game", code)
                    .append_pair("preferedmode", "offline")
                    .append_pair("real", "0")
                    .finish();
                return format!(
                    "https://cachedownload.playtechone.com/ngmdesktop/casinoclient.html?{query}"
                );
            }
        }
        self.url.clone()
    }
}

fn readonly(path: &Path) -> AppResult<Connection> {
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.busy_timeout(std::time::Duration::from_secs(3))?;
    Ok(connection)
}

pub fn load_games(path: &Path) -> AppResult<(Vec<Game>, f64)> {
    let started = Instant::now();
    let connection = readonly(path)?;
    let mut statement = connection.prepare(
        "SELECT g.provider,g.slug,g.name,g.url,g.symbol,g.last_status,g.last_test_at,g.last_error,g.thumbnail_path,
         EXISTS(SELECT 1 FROM manual_validations v JOIN test_results r ON r.id=v.result_id
            WHERE r.provider=g.provider AND r.slug=g.slug AND r.id=(SELECT MAX(t.id) FROM test_results t
                WHERE t.provider=g.provider AND t.slug=g.slug))
         FROM games g ORDER BY g.name COLLATE NOCASE")?;
    let rows = statement.query_map([], |row| {
        let provider: String = row.get(0)?;
        let slug: String = row.get(1)?;
        let name: String = row.get(2)?;
        let symbol: String = row.get(4)?;
        let manual: bool = row.get(9)?;
        Ok(Game {
            search_text: format!("{name} {symbol} {slug} {provider}").to_lowercase(),
            provider,
            slug,
            name,
            symbol,
            url: row.get(3)?,
            status: if manual {
                "OK MANUAL".into()
            } else {
                row.get(5)?
            },
            tested: row.get(6)?,
            error: row.get(7)?,
            thumbnail: row.get(8)?,
        })
    })?;
    let games = rows.collect::<Result<Vec<_>, _>>()?;
    Ok((games, started.elapsed().as_secs_f64() * 1000.0))
}

#[derive(Clone, Debug, Default)]
pub struct Details {
    pub error: String,
    pub elapsed_ms: Option<f64>,
    pub success: u64,
    pub failed: u64,
    pub requested: u64,
    pub modes: Vec<(String, String)>,
    pub run_dir: Option<PathBuf>,
}

pub fn load_details(path: &Path, game: &Game) -> AppResult<Details> {
    use rusqlite::OptionalExtension;
    let connection = readonly(path)?;
    let payload: Option<String> = connection.query_row(
        "SELECT payload_json FROM test_results WHERE provider=?1 AND slug=?2 ORDER BY id DESC LIMIT 1",
        [&game.provider, &game.slug], |row| row.get(0)).optional()?;
    let Some(payload) = payload else {
        return Ok(Details::default());
    };
    let value: serde_json::Value = serde_json::from_str(&payload)?;
    let modes = value["discovered_modes"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|mode| {
            (
                mode["label"]
                    .as_str()
                    .or(mode["name"].as_str())
                    .or(mode["id"].as_str())
                    .unwrap_or("Sin nombre")
                    .to_owned(),
                mode["kind"].as_str().unwrap_or("Sin clasificar").to_owned(),
            )
        })
        .collect();
    Ok(Details {
        error: value["error"].as_str().unwrap_or("").to_owned(),
        elapsed_ms: value["elapsed_ms"].as_f64(),
        success: value["successful_spins"].as_u64().unwrap_or(0),
        failed: value["failed_spins"].as_u64().unwrap_or(0),
        requested: value["requested_spins"].as_u64().unwrap_or(0),
        modes,
        run_dir: value["run_dir"].as_str().map(PathBuf::from),
    })
}

pub fn visible_indices(games: &[Game], provider: &str, status: &str, search: &str) -> Vec<usize> {
    let words: Vec<String> = search.split_whitespace().map(str::to_lowercase).collect();
    games
        .iter()
        .enumerate()
        .filter(|(_, game)| {
            (provider.is_empty() || game.provider == provider)
                && (status.is_empty() || game.status == status)
                && words.iter().all(|word| game.search_text.contains(word))
        })
        .map(|(index, _)| index)
        .collect()
}

pub fn firefox_path() -> Option<PathBuf> {
    for variable in ["ProgramFiles", "ProgramFiles(x86)"] {
        if let Some(base) = std::env::var_os(variable) {
            let path = PathBuf::from(base).join("Mozilla Firefox/firefox.exe");
            if path.is_file() {
                return Some(path);
            }
        }
    }
    for base in std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()) {
        let path = base.join(if cfg!(windows) {
            "firefox.exe"
        } else {
            "firefox"
        });
        if path.is_file() {
            return Some(path);
        }
    }
    None
}

pub fn open_firefox(game: &Game) -> AppResult<()> {
    let url = game.launch_url();
    let parsed = url::Url::parse(&url)?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err("El juego no tiene un enlace web válido".into());
    }
    let executable = firefox_path().ok_or("No se encontró Firefox")?;
    std::process::Command::new(executable)
        .args(["-new-tab", &url])
        .spawn()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn game() -> Game {
        Game {
            provider: "elk".into(),
            slug: "sample".into(),
            name: "Sample".into(),
            url: "https://example.com/demo".into(),
            symbol: "abc".into(),
            status: "PARCIAL".into(),
            tested: String::new(),
            error: String::new(),
            thumbnail: String::new(),
            search_text: "sample abc elk".into(),
        }
    }
    #[test]
    fn filters_are_local_and_composable() {
        let games = vec![game()];
        assert_eq!(
            visible_indices(&games, "elk", "PARCIAL", "SAMPLE abc"),
            vec![0]
        );
        assert!(visible_indices(&games, "elk", "OK", "").is_empty());
        assert!(visible_indices(&games, "", "", "missing").is_empty());
    }
    #[test]
    fn launch_uses_offline_playtech_mode_and_encodes_identity() {
        let mut g = game();
        g.provider = "playtech".into();
        g.symbol = "game&other".into();
        let url = url::Url::parse(&g.launch_url()).unwrap();
        let params: std::collections::HashMap<_, _> = url.query_pairs().into_owned().collect();
        assert_eq!(params["game"], "game&other");
        assert_eq!(params["real"], "0");
    }
    #[test]
    fn database_reads_do_not_mutate_data_and_keep_manual_status() {
        let directory = Path::new(env!("CARGO_MANIFEST_DIR")).join("evidence");
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join(format!("test-{}.sqlite", std::process::id()));
        {
            let c = Connection::open(&path).unwrap();
            c.execute_batch("CREATE TABLE games(provider,slug,name,url,symbol,last_status,last_test_at,last_error,thumbnail_path);
             CREATE TABLE test_results(id INTEGER PRIMARY KEY,provider,slug,payload_json);
             CREATE TABLE manual_validations(result_id,approved_at,note);
             INSERT INTO games VALUES('elk','sample','Sample','https://example.com/demo','','PARCIAL','','','');
             INSERT INTO test_results VALUES(1,'elk','sample','{\"requested_spins\":1,\"successful_spins\":1}');
             INSERT INTO manual_validations VALUES(1,'today','checked');").unwrap();
        }
        let before = std::fs::read(&path).unwrap();
        let (games, _) = load_games(&path).unwrap();
        assert_eq!(games[0].status, "OK MANUAL");
        assert_eq!(load_details(&path, &games[0]).unwrap().success, 1);
        assert_eq!(before, std::fs::read(&path).unwrap());
        std::fs::remove_file(path).unwrap();
    }
}
