// UNVERIFIED: not compiled. Relays framed JSON-RPC between the webview and the Python sidecar (`python -m screen2code.server.main`).
// The webview never gets a shell or file-system API: its only capabilities are s2c_send / s2c_poll, and the sidecar enforces its own
// parameter validation and project confinement. A packaged build replaces the `python` command with the signed --onedir sidecar executable.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};

struct Sidecar {
    stdin: Mutex<ChildStdin>,
    inbox: Arc<Mutex<Vec<String>>>,
    _child: Mutex<Child>,
}

#[tauri::command]
fn s2c_send(state: tauri::State<Sidecar>, message: String) -> Result<(), String> {
    let mut stdin = state.stdin.lock().map_err(|e| e.to_string())?;
    let frame = format!("Content-Length: {}\r\n\r\n{}", message.len(), message);
    stdin.write_all(frame.as_bytes()).map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())
}

#[tauri::command]
fn s2c_poll(state: tauri::State<Sidecar>) -> Vec<String> {
    std::mem::take(&mut *state.inbox.lock().unwrap())
}

fn spawn_sidecar() -> Sidecar {
    let exe = std::env::var("S2C_SIDECAR").unwrap_or_else(|_| "python".into());
    let args: Vec<String> = if exe == "python" { vec!["-m".into(), "screen2code.server.main".into()] } else { vec!["serve".into()] };
    let mut child = Command::new(exe).args(args).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().expect("failed to start the Screen2Code sidecar");
    let stdin = child.stdin.take().unwrap();
    let mut out = BufReader::new(child.stdout.take().unwrap());
    let inbox = Arc::new(Mutex::new(Vec::new()));
    let sink = inbox.clone();
    std::thread::spawn(move || loop {
        let mut len = 0usize;
        loop {
            let mut line = String::new();
            if out.read_line(&mut line).unwrap_or(0) == 0 { return; }
            let l = line.trim();
            if l.is_empty() { break; }
            if let Some(v) = l.to_ascii_lowercase().strip_prefix("content-length:") { len = v.trim().parse().unwrap_or(0); }
        }
        let mut body = vec![0u8; len];
        if out.read_exact(&mut body).is_err() { return; }
        sink.lock().unwrap().push(String::from_utf8_lossy(&body).into_owned());
    });
    Sidecar { stdin: Mutex::new(stdin), inbox, _child: Mutex::new(child) }
}

fn main() {
    tauri::Builder::default()
        .manage(spawn_sidecar())
        .invoke_handler(tauri::generate_handler![s2c_send, s2c_poll])
        .run(tauri::generate_context!())
        .expect("error while running Screen2Code");
}
