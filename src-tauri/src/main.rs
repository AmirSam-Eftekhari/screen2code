// Development shell: relays framed JSON-RPC between the webview and the Python sidecar.
// The webview receives no general shell or filesystem API. The sidecar must still enforce
// its own parameter validation and project confinement. Packaged sidecar distribution is
// not implemented; S2C_SIDECAR is reserved for that future packaging path.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};

const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;
const MAX_HEADER_BYTES: usize = 8 * 1024;
const MAX_QUEUED_MESSAGES: usize = 256;

struct Sidecar {
    stdin: Mutex<ChildStdin>,
    inbox: Arc<Mutex<Vec<String>>>,
    child: Mutex<Child>,
}

impl Drop for Sidecar {
    fn drop(&mut self) {
        // Do not leave the Python sidecar running after the desktop shell exits.
        if let Ok(child) = self.child.get_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[tauri::command]
fn s2c_send(state: tauri::State<Sidecar>, message: String) -> Result<(), String> {
    let bytes = message.as_bytes();
    if bytes.len() > MAX_FRAME_BYTES {
        return Err(format!("JSON-RPC message exceeds the {MAX_FRAME_BYTES}-byte limit"));
    }

    let mut stdin = state.stdin.lock().map_err(|e| e.to_string())?;
    let header = format!("Content-Length: {}\r\n\r\n", bytes.len());
    stdin.write_all(header.as_bytes()).map_err(|e| e.to_string())?;
    stdin.write_all(bytes).map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())
}

#[tauri::command]
fn s2c_poll(state: tauri::State<Sidecar>) -> Vec<String> {
    match state.inbox.lock() {
        Ok(mut inbox) => std::mem::take(&mut *inbox),
        Err(_) => Vec::new(),
    }
}

fn spawn_sidecar() -> Sidecar {
    let exe = std::env::var("S2C_SIDECAR").unwrap_or_else(|_| "python".into());
    let args: Vec<String> = if exe == "python" {
        vec!["-m".into(), "screen2code.server.main".into()]
    } else {
        vec!["serve".into()]
    };

    let mut child = Command::new(exe)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("failed to start the Screen2Code sidecar");

    let stdin = child.stdin.take().expect("sidecar stdin was not piped");
    let stdout = child.stdout.take().expect("sidecar stdout was not piped");
    let inbox = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&inbox);

    std::thread::spawn(move || {
        let mut out = BufReader::new(stdout);
        loop {
            let mut content_length: Option<usize> = None;
            let mut header_bytes = 0usize;

            loop {
                let mut line = String::new();
                let read = match out.read_line(&mut line) {
                    Ok(n) if n > 0 => n,
                    _ => return,
                };
                header_bytes = match header_bytes.checked_add(read) {
                    Some(n) if n <= MAX_HEADER_BYTES => n,
                    _ => return,
                };

                let trimmed = line.trim();
                if trimmed.is_empty() {
                    break;
                }

                if let Some(value) = trimmed.to_ascii_lowercase().strip_prefix("content-length:") {
                    if content_length.is_some() {
                        return;
                    }
                    let parsed = match value.trim().parse::<usize>() {
                        Ok(n) if n <= MAX_FRAME_BYTES => n,
                        _ => return,
                    };
                    content_length = Some(parsed);
                }
            }

            let len = match content_length {
                Some(n) => n,
                None => return,
            };
            let mut body = vec![0u8; len];
            if out.read_exact(&mut body).is_err() {
                return;
            }
            let message = match String::from_utf8(body) {
                Ok(text) => text,
                Err(_) => return,
            };

            let mut queue = match sink.lock() {
                Ok(queue) => queue,
                Err(_) => return,
            };
            if queue.len() >= MAX_QUEUED_MESSAGES {
                // Fail closed rather than allowing an unbounded response queue.
                return;
            }
            queue.push(message);
        }
    });

    Sidecar {
        stdin: Mutex::new(stdin),
        inbox,
        child: Mutex::new(child),
    }
}

fn main() {
    tauri::Builder::default()
        .manage(spawn_sidecar())
        .invoke_handler(tauri::generate_handler![s2c_send, s2c_poll])
        .run(tauri::generate_context!())
        .expect("error while running Screen2Code");
}
