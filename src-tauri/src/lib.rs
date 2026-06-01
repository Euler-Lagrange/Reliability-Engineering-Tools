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

#[cfg(target_os = "windows")]
mod windows_job {
    use std::{io, os::windows::io::AsRawHandle, process::Child, ptr};
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    // NtResumeProcess is an undocumented but stable-across-versions NT API
    // (available since NT 4.0). Used to resume a sidecar spawned with
    // CREATE_SUSPENDED after it has been assigned to the Job Object, so the
    // child never runs outside the job even for a single scheduler tick.
    #[link(name = "ntdll")]
    extern "system" {
        fn NtResumeProcess(process: HANDLE) -> i32;
    }

    /// Windows `CREATE_SUSPENDED` flag for `CommandExt::creation_flags`.
    pub const CREATE_SUSPENDED: u32 = 0x0000_0004;

    pub struct WindowsJobObject(HANDLE);

    // SAFETY: a Windows Job Object HANDLE is a kernel handle — the OS
    // serialises access to its handle table. This type is only shared
    // through Arc<Mutex<Option<ManagedSidecar>>>, so CloseHandle never
    // races itself.
    unsafe impl Send for WindowsJobObject {}
    unsafe impl Sync for WindowsJobObject {}

    /// Resume every thread of a child process that was spawned with
    /// `CREATE_SUSPENDED`. Called by the bridge after the child has been
    /// safely assigned to the Job Object, so there is no window in which the
    /// child runs outside the job.
    pub fn resume_child(child: &Child) -> Result<(), String> {
        let handle = child.as_raw_handle() as HANDLE;
        // NTSTATUS values >= 0 mean success.
        let status = unsafe { NtResumeProcess(handle) };
        if status < 0 {
            return Err(format!(
                "Failed to resume sidecar after job-object assignment (NTSTATUS 0x{:08x})",
                status as u32
            ));
        }
        Ok(())
    }

    impl WindowsJobObject {
        pub fn create() -> Result<Self, String> {
            let handle = unsafe { CreateJobObjectW(ptr::null(), ptr::null()) };
            if handle.is_null() {
                return Err(format!(
                    "Failed to create Windows Job Object: {}",
                    io::Error::last_os_error()
                ));
            }

            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

            let status = unsafe {
                SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &mut info as *mut _ as *mut _,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
            };
            if status == 0 {
                unsafe {
                    CloseHandle(handle);
                }
                return Err(format!(
                    "Failed to configure Windows Job Object: {}",
                    io::Error::last_os_error()
                ));
            }

            Ok(Self(handle))
        }

        pub fn assign_child(&self, child: &Child) -> Result<(), String> {
            let process_handle = child.as_raw_handle() as HANDLE;
            let status = unsafe { AssignProcessToJobObject(self.0, process_handle) };
            if status == 0 {
                return Err(format!(
                    "Failed to assign sidecar to Windows Job Object: {}",
                    io::Error::last_os_error()
                ));
            }
            Ok(())
        }
    }

    impl Drop for WindowsJobObject {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe {
                    CloseHandle(self.0);
                }
            }
        }
    }
}

#[cfg(target_os = "windows")]
use windows_job::{resume_child, WindowsJobObject, CREATE_SUSPENDED};

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
    // Absolute path to the sidecar log directory. Surfaced to the frontend
    // so Settings > Logs can reveal the real path instead of a placeholder.
    #[serde(skip_serializing_if = "Option::is_none")]
    log_directory: Option<String>,
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
    rows_scanned: u32,
    columns_scanned: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    header_rows_scanned: Option<u32>,
    row_cap_applied: bool,
    column_cap_applied: bool,
    header_search_cap_applied: bool,
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
    rows_scanned: u32,
    // Diagnostic: how many rows were scanned while searching for the header
    // row. Emitted by Python `analyze_template`; `None` if the field is
    // missing from the sidecar payload (older sidecars).
    #[serde(skip_serializing_if = "Option::is_none")]
    header_rows_scanned: Option<u32>,
    columns_scanned: u32,
    row_cap_applied: bool,
    column_cap_applied: bool,
    header_search_cap_applied: bool,
    mode: String,
}

#[derive(Serialize)]
struct BackendSessionStatusResponse {
    connected: bool,
    mode: String,
    backend: String,
    session_generation: u64,
}

#[derive(Serialize)]
struct RunAcceptedResponse {
    run_id: String,
    mode: String,
    session_generation: u64,
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
    #[cfg(target_os = "windows")]
    // Held for RAII: closing the job object reaps the sidecar process tree.
    #[allow(dead_code)]
    job_object: Arc<WindowsJobObject>,
}

impl ManagedSidecar {
    fn kill(&self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

type SessionSlot = Arc<Mutex<Option<ManagedSidecar>>>;

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
    session_generation: Mutex<u64>,
    fatal_sidecar_detail: Mutex<Option<String>>,
}

impl SessionShared {
    fn new() -> Self {
        Self {
            pending: Mutex::new(HashMap::new()),
            connected: Mutex::new(false),
            app_handle: Mutex::new(None),
            last_heartbeat: Mutex::new(None),
            session_generation: Mutex::new(0),
            fatal_sidecar_detail: Mutex::new(None),
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

    fn current_session_generation(&self) -> u64 {
        self.session_generation
            .lock()
            .map(|guard| *guard)
            .unwrap_or_default()
    }

    fn advance_session_generation(&self) -> u64 {
        if let Ok(mut guard) = self.session_generation.lock() {
            *guard += 1;
            *guard
        } else {
            0
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

    fn clear_fatal_sidecar_detail(&self) {
        if let Ok(mut guard) = self.fatal_sidecar_detail.lock() {
            *guard = None;
        }
    }

    fn record_fatal_sidecar_detail(&self, detail: String) {
        if let Ok(mut guard) = self.fatal_sidecar_detail.lock() {
            *guard = Some(detail);
        }
    }

    fn take_fatal_sidecar_detail(&self) -> Option<String> {
        self.fatal_sidecar_detail
            .lock()
            .ok()
            .and_then(|mut guard| guard.take())
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
        if let Ok(mut heartbeat_guard) = self.last_heartbeat.lock() {
            *heartbeat_guard = None;
        }
        let message = merge_disconnect_message(&message, self.take_fatal_sidecar_detail().as_deref());
        self.fail_all_pending(&message);
        if was_connected {
            self.emit_session_event("disconnected", &message);
        }
    }
}

fn kill_managed_session(session: &SessionSlot) {
    if let Ok(mut session_guard) = session.lock() {
        if let Some(active_session) = session_guard.take() {
            active_session.kill();
        }
    }
}

fn disconnect_managed_session(session: &SessionSlot, shared: &Arc<SessionShared>, message: String) {
    kill_managed_session(session);
    shared.handle_disconnect(message);
}

struct SidecarState {
    session: SessionSlot,
    shared: Arc<SessionShared>,
}

impl SidecarState {
    fn new() -> Self {
        Self {
            session: Arc::new(Mutex::new(None)),
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

            let session = spawn_managed_sidecar(self.session.clone(), self.shared.clone())?;
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
            session_generation: self.shared.current_session_generation(),
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
            session_generation: self.shared.current_session_generation(),
        }
    }

    fn force_disconnect(&self, message: &str) {
        disconnect_managed_session(&self.session, &self.shared, message.to_string());
    }

    fn shutdown(&self) {
        self.shared.set_connected(false);
        self.shared.fail_all_pending("Desktop shell is shutting down.");
        kill_managed_session(&self.session);
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

fn spawn_stdout_reader(stdout: ChildStdout, shared: Arc<SessionShared>, session: SessionSlot) {
    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();

        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) => {
                    disconnect_managed_session(
                        &session,
                        &shared,
                        "Python sidecar closed stdout.".to_string(),
                    );
                    break;
                }
                Ok(_) => {
                    let trimmed = line.trim();
                    if trimmed.is_empty() {
                        continue;
                    }

                    let mut parsed: Value = match serde_json::from_str(trimmed) {
                        Ok(value) => value,
                        Err(error) => {
                            disconnect_managed_session(
                                &session,
                                &shared,
                                format!(
                                "Python sidecar emitted invalid JSON: {error}. Line: {trimmed}"
                                ),
                            );
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
                    let has_request_id = request_id.is_some();
                    let has_run_id = run_id.is_some();

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

                    if kind == "log" && run_id.is_none() {
                        let payload = parsed.get("payload");
                        let level = payload
                            .and_then(|value| value.get("level"))
                            .and_then(Value::as_str);
                        let line = payload
                            .and_then(|value| value.get("line").or_else(|| value.get("message")))
                            .and_then(Value::as_str);
                        // Only merge lines that look like a last-gasp crash envelope
                        // from the Python excepthooks; otherwise a routine error log
                        // from ten seconds ago would be quoted into the next
                        // unrelated disconnect message.
                        if level == Some("error") {
                            if let Some(line) = line {
                                if line.starts_with("Unhandled exception:")
                                    || line.starts_with("Unhandled thread exception")
                                {
                                    shared.record_fatal_sidecar_detail(line.to_string());
                                }
                            }
                        }
                    }

                    match kind.as_str() {
                        "heartbeat" => {
                            shared.record_heartbeat();
                        }
                        "ack" | "status" | "progress" | "log" | "result" | "backend_error" | "cancelled" => {
                            if should_forward_run_event(&kind, has_request_id, has_run_id) {
                                enrich_run_event_for_frontend(
                                    &mut parsed,
                                    shared.current_session_generation(),
                                );
                                shared.emit_run_event(&parsed);
                            }
                        }
                        _ => {}
                    }
                }
                Err(error) => {
                    disconnect_managed_session(
                        &session,
                        &shared,
                        format!("Failed while waiting for python sidecar output: {error}"),
                    );
                    break;
                }
            }
        }
    });
}

fn spawn_heartbeat_supervisor(shared: Arc<SessionShared>, session: SessionSlot) {
    thread::spawn(move || {
        loop {
            thread::sleep(HEARTBEAT_CHECK_INTERVAL);

            if !shared.is_connected() {
                break;
            }

            if shared.heartbeat_overdue() {
                disconnect_managed_session(
                    &session,
                    &shared,
                    "Python sidecar heartbeat timed out — backend may have crashed or hung.".to_string(),
                );
                break;
            }
        }
    });
}

fn should_forward_run_event(kind: &str, has_request_id: bool, has_run_id: bool) -> bool {
    if !has_run_id {
        return false;
    }

    match kind {
        // The execute_run ack is both a command response and the first
        // lifecycle event; the frontend expects to see it after enrichment.
        "ack" => true,
        // Other request-correlated messages are command responses, such as
        // cancel_run's `result { status: "cancelling" }`, and must not be
        // replayed as streamed run events.
        "status" | "progress" | "log" | "result" | "backend_error" | "cancelled" => {
            !has_request_id
        }
        _ => false,
    }
}

fn enrich_run_event_for_frontend(event: &mut Value, session_generation: u64) {
    if event.get("kind").and_then(Value::as_str) != Some("ack") {
        return;
    }

    let Some(envelope) = event.as_object_mut() else {
        return;
    };

    let payload = envelope.entry("payload").or_insert_with(|| json!({}));
    if !payload.is_object() {
        *payload = json!({});
    }

    if let Some(payload) = payload.as_object_mut() {
        payload
            .entry("mode".to_string())
            .or_insert_with(|| json!("desktop-bridge"));
        payload.insert("session_generation".to_string(), json!(session_generation));
    }
}

fn correlation_id(prefix: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!("{prefix}_{nanos}")
}

fn merge_disconnect_message(base: &str, detail: Option<&str>) -> String {
    let base = base.trim();
    let detail = detail.map(str::trim).filter(|value| !value.is_empty());

    match (base.is_empty(), detail) {
        (true, Some(detail)) => detail.to_string(),
        (false, Some(detail)) if base.contains(detail) => base.to_string(),
        (false, Some(detail)) => format!("{base} Details: {detail}"),
        _ => base.to_string(),
    }
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

fn spawn_managed_sidecar(session: SessionSlot, shared: Arc<SessionShared>) -> Result<ManagedSidecar, String> {
    // On Windows, create the Job Object BEFORE spawning the child, then spawn
    // the child with CREATE_SUSPENDED, assign to the job, and only then resume.
    // This eliminates two orphan-the-child races:
    //   (a) WindowsJobObject::create() failing after the child is already live.
    //   (b) The parent panicking between spawn() and AssignProcessToJobObject.
    // With CREATE_SUSPENDED the child's primary thread is suspended until after
    // the job has accepted it, so it can never run outside the job even for a
    // single scheduler tick.
    #[cfg(target_os = "windows")]
    let job = WindowsJobObject::create()?;

    let mut child = if let Some(bundled) = resolve_bundled_sidecar() {
        // Production: bundled PyInstaller sidecar exe
        let mut command = Command::new(&bundled);
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(CREATE_SUSPENDED);
        }
        command.spawn().map_err(|error| {
            format!("Failed to start bundled sidecar '{}': {error}", bundled.display())
        })?
    } else {
        // Development: python interpreter + script
        let python = resolve_python_interpreter();
        let script = resolve_sidecar_script()?;
        let mut command = Command::new(&python);
        command
            .arg(&script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(CREATE_SUSPENDED);
        }
        command.spawn().map_err(|error| {
            format!(
                "Failed to start python sidecar using '{}' and '{}': {error}",
                python.display(),
                script.display()
            )
        })?
    };

    #[cfg(target_os = "windows")]
    let job_object = {
        if let Err(error) = job.assign_child(&child) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
        if let Err(error) = resume_child(&child) {
            // Assign succeeded but resume failed: the suspended child is now
            // owned by the job, so killing it here is safe and bounded.
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
        Arc::new(job)
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
    let session_generation = shared.advance_session_generation();
    shared.set_connected(true);
    shared.clear_fatal_sidecar_detail();
    shared.record_heartbeat(); // Seed initial heartbeat so supervisor doesn't fire immediately
    shared.emit_session_event(
        "connected",
        &format!("Python sidecar session ready (generation {session_generation})."),
    );
    spawn_stdout_reader(stdout, shared.clone(), session.clone());
    spawn_heartbeat_supervisor(shared, session);

    Ok(ManagedSidecar {
        child,
        stdin: Arc::new(Mutex::new(stdin)),
        #[cfg(target_os = "windows")]
        job_object,
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
        log_directory: payload
            .get("log_directory")
            .and_then(Value::as_str)
            .map(str::to_string),
    })
}

#[tauri::command]
fn backend_session_status(state: tauri::State<'_, SidecarState>) -> BackendSessionStatusResponse {
    state.session_status()
}

/// Open ``path`` in the host OS file manager.
///
/// Windows: spawns ``explorer.exe`` on the path (opens folders, highlights
/// files). macOS: ``open``. Linux: ``xdg-open``. Returns ``Err`` if the
/// path does not exist or the spawn fails — callers should surface the
/// error via a notification. Intended for small affordances like
/// "Open log folder" and "Reveal output" and does NOT require adding the
/// opener plugin to Cargo.toml.
#[tauri::command]
fn reveal_in_file_manager(path: String) -> Result<(), String> {
    let target = Path::new(&path);
    if !target.exists() {
        return Err(format!("Path does not exist: {path}"));
    }

    #[cfg(target_os = "windows")]
    let spawn_result = if target.is_file() {
        Command::new("explorer")
            .arg(format!("/select,{}", target.display()))
            .spawn()
    } else {
        Command::new("explorer").arg(target).spawn()
    };

    #[cfg(target_os = "macos")]
    let spawn_result = if target.is_file() {
        Command::new("open").arg("-R").arg(target).spawn()
    } else {
        Command::new("open").arg(target).spawn()
    };

    #[cfg(all(not(target_os = "windows"), not(target_os = "macos")))]
    let parent = target.parent().unwrap_or(target);

    #[cfg(all(not(target_os = "windows"), not(target_os = "macos")))]
    let spawn_result = Command::new("xdg-open")
        .arg(if target.is_file() { parent } else { target })
        .spawn();

    spawn_result
        .map(|_| ())
        .map_err(|err| format!("Failed to reveal path: {err}"))
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
        rows_scanned: payload
            .get("rows_scanned")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        columns_scanned: payload
            .get("columns_scanned")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        header_rows_scanned: payload
            .get("header_rows_scanned")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
        row_cap_applied: payload
            .get("row_cap_applied")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        column_cap_applied: payload
            .get("column_cap_applied")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        header_search_cap_applied: payload
            .get("header_search_cap_applied")
            .and_then(Value::as_bool)
            .unwrap_or(false),
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
        rows_scanned: payload
            .get("rows_scanned")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        header_rows_scanned: payload
            .get("header_rows_scanned")
            .and_then(Value::as_u64)
            .map(|v| v as u32),
        columns_scanned: payload
            .get("columns_scanned")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        row_cap_applied: payload
            .get("row_cap_applied")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        column_cap_applied: payload
            .get("column_cap_applied")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        header_search_cap_applied: payload
            .get("header_search_cap_applied")
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

/// Resolve the sidecar log directory using the same precedence as the
/// Python side (``common/logger.py::get_log_directory``): first
/// ``RELIABILITY_TOOLS_LOG_DIR``, then ``~/.reliability_tools/logs``. Kept
/// zero-dependency — we only need ``USERPROFILE`` / ``HOME`` which are
/// always present on supported platforms.
fn resolve_log_directory() -> Option<PathBuf> {
    if let Ok(custom) = env::var("RELIABILITY_TOOLS_LOG_DIR") {
        if !custom.is_empty() {
            return Some(PathBuf::from(custom));
        }
    }
    let home = env::var("USERPROFILE")
        .or_else(|_| env::var("HOME"))
        .ok()?;
    if home.is_empty() {
        return None;
    }
    Some(PathBuf::from(home).join(".reliability_tools").join("logs"))
}

/// Install a panic hook that writes a crash dump alongside the Python
/// sidecar's crash dumps so a user hitting a Rust-side panic can share a
/// single folder with us. Best-effort — if the filesystem write fails we
/// fall back to the default panic printer. We deliberately keep this hook
/// short to avoid re-entering panics while a panic is in flight.
fn install_rust_panic_hook() {
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |panic_info| {
        if let Some(log_dir) = resolve_log_directory() {
            let crash_dir = log_dir.join("crashes");
            let _ = std::fs::create_dir_all(&crash_dir);

            let timestamp = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_millis())
                .unwrap_or(0);
            let dump_path = crash_dir.join(format!("crash_rust_{timestamp}.log"));

            let payload = if let Some(s) = panic_info.payload().downcast_ref::<&str>() {
                (*s).to_string()
            } else if let Some(s) = panic_info.payload().downcast_ref::<String>() {
                s.clone()
            } else {
                "<non-string panic payload>".to_string()
            };

            let location = panic_info
                .location()
                .map(|l| format!("{}:{}:{}", l.file(), l.line(), l.column()))
                .unwrap_or_else(|| "<unknown>".to_string());

            let contents = format!(
                "Crash dump: rust\nTimestamp:  {ts}ms since epoch\nLocation:   {loc}\nPayload:    {payload}\n",
                ts = timestamp,
                loc = location,
                payload = payload,
            );

            if let Ok(mut f) = std::fs::File::create(&dump_path) {
                let _ = f.write_all(contents.as_bytes());
            }
        }
        default_hook(panic_info);
    }));
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    install_rust_panic_hook();

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

    let app = tauri::Builder::default()
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
            backend_read_flet_config,
            reveal_in_file_manager
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<SidecarState>();
                state.inner().shutdown();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Reliability Tools Desktop");

    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let state = app_handle.state::<SidecarState>();
            state.inner().shutdown();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{
        enrich_run_event_for_frontend, merge_disconnect_message, should_forward_run_event,
    };
    use serde_json::json;

    #[test]
    fn merge_disconnect_message_appends_fatal_detail() {
        let message = merge_disconnect_message(
            "Python sidecar closed stdout.",
            Some("Unhandled exception: RuntimeError: boom"),
        );

        assert_eq!(
            message,
            "Python sidecar closed stdout. Details: Unhandled exception: RuntimeError: boom"
        );
    }

    #[test]
    fn merge_disconnect_message_avoids_duplicate_detail() {
        let message = merge_disconnect_message(
            "Python sidecar closed stdout. Details: Unhandled exception: RuntimeError: boom",
            Some("Unhandled exception: RuntimeError: boom"),
        );

        assert_eq!(
            message,
            "Python sidecar closed stdout. Details: Unhandled exception: RuntimeError: boom"
        );
    }

    #[test]
    fn enrich_run_event_adds_ack_session_generation() {
        let mut event = json!({
            "kind": "ack",
            "run_id": "run_001",
            "payload": {
                "accepted": true,
                "run_id": "run_001"
            }
        });

        enrich_run_event_for_frontend(&mut event, 7);

        assert_eq!(event["payload"]["session_generation"], json!(7));
        assert_eq!(event["payload"]["mode"], json!("desktop-bridge"));
    }

    #[test]
    fn enrich_run_event_leaves_non_ack_payloads_alone() {
        let mut event = json!({
            "kind": "progress",
            "run_id": "run_001",
            "payload": {
                "stage": "Working"
            }
        });

        enrich_run_event_for_frontend(&mut event, 7);

        assert!(event["payload"].get("session_generation").is_none());
        assert_eq!(event["payload"], json!({ "stage": "Working" }));
    }

    #[test]
    fn run_event_forwarding_filters_command_result_responses() {
        assert!(should_forward_run_event("ack", true, true));
        assert!(should_forward_run_event("result", false, true));
        assert!(should_forward_run_event("status", false, true));

        assert!(!should_forward_run_event("result", true, true));
        assert!(!should_forward_run_event("status", true, true));
        assert!(!should_forward_run_event("result", false, false));
    }
}
