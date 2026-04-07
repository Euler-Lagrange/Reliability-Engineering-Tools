use serde::Serialize;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    env,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, Stdio},
    sync::{mpsc, Arc, Mutex},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Emitter, Manager};

const PROTOCOL_VERSION: &str = "0.1.0";
const BACKEND_RUN_EVENT: &str = "backend://run-event";
const BACKEND_SESSION_EVENT: &str = "backend://session";
const HEARTBEAT_TIMEOUT: Duration = Duration::from_secs(15);
const HEARTBEAT_CHECK_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Serialize)]
struct BackendHealthResponse {
    status: String,
    backend: String,
    protocol_version: String,
    mode: String,
}

#[derive(Serialize)]
struct SheetListResponse {
    path: String,
    sheets: Vec<String>,
    mode: String,
}

#[derive(Serialize)]
struct InputInspectionResponse {
    path: String,
    sheet: String,
    header_row: u32,
    row_count: u32,
    columns: Vec<String>,
    preview_rows: Vec<std::collections::BTreeMap<String, String>>,
    mode: String,
}

#[derive(Serialize)]
struct TemplateAnalysisResponse {
    path: String,
    sheet: String,
    header_row: u32,
    columns: Vec<String>,
    merged_range_count: u32,
    freeze_panes: Option<String>,
    protected_sheet: bool,
    mode: String,
}

#[derive(Serialize)]
struct BackendSessionStatusResponse {
    connected: bool,
    mode: String,
    backend: String,
}

#[derive(Serialize)]
struct RunAcceptedResponse {
    run_id: String,
    mode: String,
}

#[derive(Serialize)]
struct CancelRunResponse {
    accepted: bool,
    run_id: String,
    status: String,
    mode: String,
}

#[derive(Clone)]
struct ManagedSidecar {
    child: Arc<Mutex<Child>>,
    stdin: Arc<Mutex<ChildStdin>>,
}

impl ManagedSidecar {
    fn kill(&self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
        }
    }
}

#[derive(Clone)]
struct PendingResponse {
    kind: String,
    payload: Value,
    run_id: Option<String>,
}

struct SessionShared {
    pending: Mutex<HashMap<String, mpsc::Sender<Result<PendingResponse, String>>>>,
    connected: Mutex<bool>,
    app_handle: Mutex<Option<AppHandle>>,
    last_heartbeat: Mutex<Option<Instant>>,
}

impl SessionShared {
    fn new() -> Self {
        Self {
            pending: Mutex::new(HashMap::new()),
            connected: Mutex::new(false),
            app_handle: Mutex::new(None),
            last_heartbeat: Mutex::new(None),
        }
    }

    fn set_app_handle(&self, app_handle: AppHandle) {
        if let Ok(mut handle_guard) = self.app_handle.lock() {
            *handle_guard = Some(app_handle);
        }
    }

    fn register_pending(
        &self,
        request_id: String,
    ) -> Result<mpsc::Receiver<Result<PendingResponse, String>>, String> {
        let (sender, receiver) = mpsc::channel();
        let mut pending = self
            .pending
            .lock()
            .map_err(|_| "Failed to lock pending request registry.".to_string())?;
        pending.insert(request_id, sender);
        Ok(receiver)
    }

    fn resolve_pending(&self, request_id: &str, response: Result<PendingResponse, String>) -> bool {
        let sender = self
            .pending
            .lock()
            .ok()
            .and_then(|mut pending| pending.remove(request_id));

        if let Some(sender) = sender {
            let _ = sender.send(response);
            return true;
        }

        false
    }

    fn fail_all_pending(&self, message: &str) {
        if let Ok(mut pending) = self.pending.lock() {
            for (_, sender) in pending.drain() {
                let _ = sender.send(Err(message.to_string()));
            }
        }
    }

    fn is_connected(&self) -> bool {
        self.connected.lock().map(|guard| *guard).unwrap_or(false)
    }

    fn set_connected(&self, connected: bool) -> bool {
        if let Ok(mut guard) = self.connected.lock() {
            let previous = *guard;
            *guard = connected;
            previous
        } else {
            false
        }
    }

    fn record_heartbeat(&self) {
        if let Ok(mut guard) = self.last_heartbeat.lock() {
            *guard = Some(Instant::now());
        }
    }

    fn heartbeat_overdue(&self) -> bool {
        if let Ok(guard) = self.last_heartbeat.lock() {
            match *guard {
                Some(last) => last.elapsed() > HEARTBEAT_TIMEOUT,
                None => false, // No heartbeat received yet — supervisor not active
            }
        } else {
            false
        }
    }

    fn emit_run_event(&self, envelope: &Value) {
        if let Ok(handle_guard) = self.app_handle.lock() {
            if let Some(app_handle) = handle_guard.as_ref() {
                let _ = app_handle.emit(BACKEND_RUN_EVENT, envelope.clone());
            }
        }
    }

    fn emit_session_event(&self, kind: &str, message: &str) {
        if let Ok(handle_guard) = self.app_handle.lock() {
            if let Some(app_handle) = handle_guard.as_ref() {
                let _ = app_handle.emit(
                    BACKEND_SESSION_EVENT,
                    json!({
                        "kind": kind,
                        "connected": kind == "connected",
                        "backend": "python-sidecar-session",
                        "message": message,
                    }),
                );
            }
        }
    }

    fn handle_disconnect(&self, message: String) {
        let was_connected = self.set_connected(false);
        self.fail_all_pending(&message);
        if was_connected {
            self.emit_session_event("disconnected", &message);
        }
    }
}

struct SidecarState {
    session: Mutex<Option<ManagedSidecar>>,
    shared: Arc<SessionShared>,
}

impl SidecarState {
    fn new() -> Self {
        Self {
            session: Mutex::new(None),
            shared: Arc::new(SessionShared::new()),
        }
    }

    fn set_app_handle(&self, app_handle: AppHandle) {
        self.shared.set_app_handle(app_handle);
    }

    fn ensure_session(&self) -> Result<ManagedSidecar, String> {
        let mut session_guard = self
            .session
            .lock()
            .map_err(|_| "Failed to lock managed sidecar session.".to_string())?;

        let needs_spawn = session_guard.is_none() || !self.shared.is_connected();
        if needs_spawn {
            if let Some(existing_session) = session_guard.take() {
                existing_session.kill();
            }

            let session = spawn_managed_sidecar(self.shared.clone())?;
            *session_guard = Some(session);
        }

        session_guard
            .as_ref()
            .cloned()
            .ok_or_else(|| "Managed sidecar session was not available after spawn.".to_string())
    }

    fn send_command_wait(
        &self,
        command_name: &str,
        body: Value,
        expected_kind: &str,
    ) -> Result<PendingResponse, String> {
        let session = self.ensure_session()?;
        let request_id = correlation_id("req");
        let receiver = self.shared.register_pending(request_id.clone())?;
        let message = json!({
            "protocol_version": PROTOCOL_VERSION,
            "id": correlation_id("cmd"),
            "kind": "command",
            "request_id": request_id,
            "run_id": Value::Null,
            "timestamp": format!("{:?}", SystemTime::now()),
            "payload": {
                "command": command_name,
                "body": body,
            }
        });

        let payload =
            serde_json::to_string(&message).map_err(|error| format!("Failed to serialize command: {error}"))?;
        let write_result = {
            let mut stdin = session
                .stdin
                .lock()
                .map_err(|_| "Failed to lock python sidecar stdin.".to_string())?;
            stdin
                .write_all(payload.as_bytes())
                .and_then(|_| stdin.write_all(b"\n"))
                .and_then(|_| stdin.flush())
        };

        if let Err(error) = write_result {
            let message = format!("Failed to send command to managed python sidecar: {error}");
            let _ = self.shared.resolve_pending(&request_id, Err(message.clone()));
            self.force_disconnect(&message);
            return Err(message);
        }

        let response = receiver
            .recv()
            .map_err(|_| "Managed python sidecar stopped before replying.".to_string())??;

        if response.kind != expected_kind {
            return Err(format!(
                "Python sidecar returned '{}' while '{}' was expected for command '{}'.",
                response.kind, expected_kind, command_name
            ));
        }

        Ok(response)
    }

    fn send_request_command(&self, command_name: &str, body: Value) -> Result<Value, String> {
        Ok(self.send_command_wait(command_name, body, "result")?.payload)
    }

    fn start_run_command(&self, body: Value) -> Result<RunAcceptedResponse, String> {
        let response = self.send_command_wait("execute_run", body, "ack")?;
        let run_id = response
            .payload
            .get("run_id")
            .and_then(Value::as_str)
            .or(response.run_id.as_deref())
            .ok_or_else(|| "Python sidecar ack did not include a run_id.".to_string())?;

        Ok(RunAcceptedResponse {
            run_id: run_id.to_string(),
            mode: response
                .payload
                .get("mode")
                .and_then(Value::as_str)
                .unwrap_or("desktop-bridge")
                .to_string(),
        })
    }

    fn cancel_run_command(&self, run_id: &str) -> Result<CancelRunResponse, String> {
        let payload = self.send_request_command("cancel_run", json!({ "run_id": run_id }))?;

        Ok(CancelRunResponse {
            accepted: payload
                .get("accepted")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            run_id: payload
                .get("run_id")
                .and_then(Value::as_str)
                .unwrap_or(run_id)
                .to_string(),
            status: payload
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("cancelling")
                .to_string(),
            mode: payload
                .get("mode")
                .and_then(Value::as_str)
                .unwrap_or("desktop-bridge")
                .to_string(),
        })
    }

    fn session_status(&self) -> BackendSessionStatusResponse {
        let connected = self.shared.is_connected();

        BackendSessionStatusResponse {
            connected,
            mode: "desktop-bridge".to_string(),
            backend: if connected {
                "python-sidecar-session".to_string()
            } else {
                "python-sidecar-session-not-started".to_string()
            },
        }
    }

    fn force_disconnect(&self, message: &str) {
        if let Ok(mut session_guard) = self.session.lock() {
            if let Some(session) = session_guard.take() {
                session.kill();
            }
        }
        self.shared.handle_disconnect(message.to_string());
    }

    fn shutdown(&self) {
        self.shared.set_connected(false);
        self.shared.fail_all_pending("Desktop shell is shutting down.");
        if let Ok(mut session_guard) = self.session.lock() {
            if let Some(session) = session_guard.take() {
                session.kill();
            }
        }
    }
}

fn spawn_stderr_logger(stderr: ChildStderr) {
    thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        let mut line = String::new();
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) => break,
                Ok(_) => {
                    let trimmed = line.trim();
                    if !trimmed.is_empty() {
                        eprintln!("[python-sidecar] {trimmed}");
                    }
                }
                Err(_) => break,
            }
        }
    });
}

fn spawn_stdout_reader(stdout: ChildStdout, shared: Arc<SessionShared>) {
    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();

        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) => {
                    shared.handle_disconnect("Python sidecar closed stdout.".to_string());
                    break;
                }
                Ok(_) => {
                    let trimmed = line.trim();
                    if trimmed.is_empty() {
                        continue;
                    }

                    let parsed: Value = match serde_json::from_str(trimmed) {
                        Ok(value) => value,
                        Err(error) => {
                            shared.handle_disconnect(format!(
                                "Python sidecar emitted invalid JSON: {error}. Line: {trimmed}"
                            ));
                            break;
                        }
                    };

                    let kind = parsed
                        .get("kind")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string();
                    let request_id = parsed.get("request_id").and_then(Value::as_str);
                    let run_id = parsed
                        .get("run_id")
                        .and_then(Value::as_str)
                        .map(ToOwned::to_owned);

                    if let Some(request_id) = request_id {
                        match kind.as_str() {
                            "ack" | "result" => {
                                let payload = parsed.get("payload").cloned().unwrap_or_else(|| json!({}));
                                let _ = shared.resolve_pending(
                                    request_id,
                                    Ok(PendingResponse {
                                        kind: kind.clone(),
                                        payload,
                                        run_id: run_id.clone(),
                                    }),
                                );
                            }
                            "error" | "backend_error" => {
                                let message = parsed
                                    .get("payload")
                                    .and_then(|payload| payload.get("message"))
                                    .and_then(Value::as_str)
                                    .unwrap_or("Python sidecar returned an unspecified error.")
                                    .to_string();
                                let _ = shared.resolve_pending(request_id, Err(message));
                            }
                            _ => {}
                        }
                    }

                    match kind.as_str() {
                        "heartbeat" => {
                            shared.record_heartbeat();
                        }
                        "ack" | "status" | "progress" | "log" | "result" | "backend_error" | "cancelled" => {
                            if run_id.is_some() {
                                shared.emit_run_event(&parsed);
                            }
                        }
                        _ => {}
                    }
                }
                Err(error) => {
                    shared.handle_disconnect(format!(
                        "Failed while waiting for python sidecar output: {error}"
                    ));
                    break;
                }
            }
        }
    });
}

fn spawn_heartbeat_supervisor(shared: Arc<SessionShared>) {
    thread::spawn(move || {
        loop {
            thread::sleep(HEARTBEAT_CHECK_INTERVAL);

            if !shared.is_connected() {
                break;
            }

            if shared.heartbeat_overdue() {
                shared.handle_disconnect(
                    "Python sidecar heartbeat timed out — backend may have crashed or hung.".to_string(),
                );
                break;
            }
        }
    });
}

fn correlation_id(prefix: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!("{prefix}_{nanos}")
}

fn find_existing_relative(relative: &str) -> Option<PathBuf> {
    let mut bases: Vec<PathBuf> = Vec::new();

    if let Ok(current_exe) = env::current_exe() {
        for ancestor in current_exe.ancestors() {
            bases.push(ancestor.to_path_buf());
        }
    }

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for ancestor in manifest_dir.ancestors() {
        bases.push(ancestor.to_path_buf());
    }

    bases
        .into_iter()
        .map(|base| base.join(relative))
        .find(|candidate| candidate.exists())
}

fn resolve_python_interpreter() -> PathBuf {
    if let Ok(custom) = env::var("RELIABILITY_TOOLS_BACKEND_PYTHON") {
        let custom_path = PathBuf::from(custom);
        if custom_path.exists() {
            return custom_path;
        }
    }

    if let Some(venv_python) = find_existing_relative(".venv/Scripts/python.exe") {
        return venv_python;
    }

    PathBuf::from("python")
}

fn resolve_sidecar_script() -> Result<PathBuf, String> {
    if let Ok(custom) = env::var("RELIABILITY_TOOLS_BACKEND_SCRIPT") {
        let custom_path = PathBuf::from(custom);
        if custom_path.exists() {
            return Ok(custom_path);
        }
    }

    find_existing_relative("backend/python/sidecar_main.py")
        .ok_or_else(|| "Could not locate backend/python/sidecar_main.py for the desktop bridge.".to_string())
}

fn resolve_bundled_sidecar() -> Option<PathBuf> {
    find_existing_relative("reliability-tools-sidecar.exe")
}

fn spawn_managed_sidecar(shared: Arc<SessionShared>) -> Result<ManagedSidecar, String> {
    let mut child = if let Some(bundled) = resolve_bundled_sidecar() {
        // Production: bundled PyInstaller sidecar exe
        Command::new(&bundled)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| {
                format!("Failed to start bundled sidecar '{}': {error}", bundled.display())
            })?
    } else {
        // Development: python interpreter + script
        let python = resolve_python_interpreter();
        let script = resolve_sidecar_script()?;
        Command::new(&python)
            .arg(&script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| {
                format!(
                    "Failed to start python sidecar using '{}' and '{}': {error}",
                    python.display(),
                    script.display()
                )
            })?
    };

    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "Python sidecar stdin was not available.".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Python sidecar stdout was not available.".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "Python sidecar stderr was not available.".to_string())?;

    spawn_stderr_logger(stderr);

    let mut stdout_reader = BufReader::new(stdout);
    let mut ready_line = String::new();
    loop {
        ready_line.clear();
        let read = stdout_reader
            .read_line(&mut ready_line)
            .map_err(|error| format!("Failed while waiting for python sidecar readiness: {error}"))?;
        if read == 0 {
            return Err("Python sidecar exited before sending a ready message.".to_string());
        }

        let trimmed = ready_line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let parsed: Value = serde_json::from_str(trimmed)
            .map_err(|error| format!("Python sidecar emitted invalid ready JSON: {error}. Line: {trimmed}"))?;
        if parsed.get("kind").and_then(Value::as_str) == Some("ready") {
            break;
        }
    }

    let child = Arc::new(Mutex::new(child));
    let stdout = stdout_reader.into_inner();
    shared.set_connected(true);
    shared.record_heartbeat(); // Seed initial heartbeat so supervisor doesn't fire immediately
    spawn_stdout_reader(stdout, shared.clone());
    spawn_heartbeat_supervisor(shared);

    Ok(ManagedSidecar {
        child,
        stdin: Arc::new(Mutex::new(stdin)),
    })
}

#[tauri::command]
fn backend_health_check(state: tauri::State<'_, SidecarState>) -> Result<BackendHealthResponse, String> {
    let payload = state.send_request_command("health_check", json!({ "app": "reliability_tools_desktop" }))?;

    Ok(BackendHealthResponse {
        status: payload
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("ok")
            .to_string(),
        backend: payload
            .get("backend")
            .and_then(Value::as_str)
            .unwrap_or("python-sidecar")
            .to_string(),
        protocol_version: payload
            .get("protocol_version")
            .and_then(Value::as_str)
            .unwrap_or(PROTOCOL_VERSION)
            .to_string(),
        mode: "desktop-bridge".to_string(),
    })
}

#[tauri::command]
fn backend_session_status(state: tauri::State<'_, SidecarState>) -> BackendSessionStatusResponse {
    state.session_status()
}

#[tauri::command]
fn backend_list_sheets(
    state: tauri::State<'_, SidecarState>,
    path: String,
) -> Result<SheetListResponse, String> {
    let normalized_path = Path::new(&path)
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(&path));
    let payload = state.send_request_command(
        "list_sheets",
        json!({
            "path": normalized_path.to_string_lossy(),
        }),
    )?;

    let sheets = payload
        .get("sheets")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(ToOwned::to_owned))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let response_path = payload
        .get("path")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| normalized_path.to_string_lossy().into_owned());

    Ok(SheetListResponse {
        path: response_path,
        sheets,
        mode: "desktop-bridge".to_string(),
    })
}

#[tauri::command]
fn backend_inspect_input(
    state: tauri::State<'_, SidecarState>,
    path: String,
    sheet: String,
    role: Option<String>,
) -> Result<InputInspectionResponse, String> {
    let normalized_path = Path::new(&path)
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(&path));
    let payload = state.send_request_command(
        "inspect_input",
        json!({
            "path": normalized_path.to_string_lossy(),
            "sheet": sheet,
            "role": role,
        }),
    )?;

    let columns = payload
        .get("columns")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(ToOwned::to_owned))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let preview_rows = payload
        .get("preview_rows")
        .and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|row| row.as_object())
                .map(|row| {
                    row.iter()
                        .filter_map(|(key, value)| value.as_str().map(|value| (key.clone(), value.to_string())))
                        .collect::<std::collections::BTreeMap<_, _>>()
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    Ok(InputInspectionResponse {
        path: payload
            .get("path")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .unwrap_or_else(|| normalized_path.to_string_lossy().into_owned()),
        sheet: payload
            .get("sheet")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        header_row: payload
            .get("header_row")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        row_count: payload
            .get("row_count")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        columns,
        preview_rows,
        mode: "desktop-bridge".to_string(),
    })
}

#[tauri::command]
fn backend_analyze_template(
    state: tauri::State<'_, SidecarState>,
    path: String,
    sheet: String,
    role: Option<String>,
) -> Result<TemplateAnalysisResponse, String> {
    let normalized_path = Path::new(&path)
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(&path));
    let payload = state.send_request_command(
        "analyze_template",
        json!({
            "path": normalized_path.to_string_lossy(),
            "sheet": sheet,
            "role": role,
        }),
    )?;

    let columns = payload
        .get("columns")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(ToOwned::to_owned))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    Ok(TemplateAnalysisResponse {
        path: payload
            .get("path")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .unwrap_or_else(|| normalized_path.to_string_lossy().into_owned()),
        sheet: payload
            .get("sheet")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        header_row: payload
            .get("header_row")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        columns,
        merged_range_count: payload
            .get("merged_range_count")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        freeze_panes: payload
            .get("freeze_panes")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned),
        protected_sheet: payload
            .get("protected_sheet")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        mode: "desktop-bridge".to_string(),
    })
}

#[tauri::command]
fn backend_validate_run(
    state: tauri::State<'_, SidecarState>,
    body: Value,
) -> Result<Value, String> {
    state.send_request_command("validate_run", body)
}

#[tauri::command]
fn backend_execute_run(
    state: tauri::State<'_, SidecarState>,
    body: Value,
) -> Result<RunAcceptedResponse, String> {
    state.start_run_command(body)
}

#[tauri::command]
fn backend_cancel_run(
    state: tauri::State<'_, SidecarState>,
    run_id: String,
) -> Result<CancelRunResponse, String> {
    state.cancel_run_command(&run_id)
}

#[tauri::command]
fn backend_read_flet_config(
    state: tauri::State<'_, SidecarState>,
    namespace: Option<String>,
) -> Result<Value, String> {
    let body = match namespace {
        Some(ns) => json!({ "namespace": ns }),
        None => json!({}),
    };
    state.send_request_command("read_flet_config", body)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    if env::args().any(|arg| arg == "--self-test") {
        println!("SELF-TEST OK: Reliability Tools Desktop {}", env!("CARGO_PKG_VERSION"));
        return;
    }

    if env::args().any(|arg| arg == "--self-test-backend") {
        let state = SidecarState::new();
        match state.send_request_command("health_check", json!({ "app": "reliability_tools_desktop" })) {
            Ok(result) => {
                println!(
                    "BACKEND SELF-TEST OK: {} {} {}",
                    result
                        .get("backend")
                        .and_then(Value::as_str)
                        .unwrap_or("python-sidecar"),
                    result
                        .get("protocol_version")
                        .and_then(Value::as_str)
                        .unwrap_or(PROTOCOL_VERSION),
                    "desktop-bridge"
                );
                state.shutdown();
            }
            Err(error) => {
                eprintln!("BACKEND SELF-TEST FAILED: {error}");
                state.shutdown();
                std::process::exit(1);
            }
        }
        return;
    }

    let sidecar_state = SidecarState::new();

    tauri::Builder::default()
        .manage(sidecar_state)
        .setup(|app| {
            let state = app.state::<SidecarState>();
            state.set_app_handle(app.handle().clone());
            Ok(())
        })
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            backend_session_status,
            backend_health_check,
            backend_list_sheets,
            backend_inspect_input,
            backend_analyze_template,
            backend_validate_run,
            backend_execute_run,
            backend_cancel_run,
            backend_read_flet_config
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<SidecarState>();
                state.inner().shutdown();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Reliability Tools Desktop");
}
