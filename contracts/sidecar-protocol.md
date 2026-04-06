# Sidecar Protocol

The Tauri shell talks to the Python backend over `stdio` using NDJSON.

## Envelope

Every message is one JSON object on one line:

```json
{
  "protocol_version": "0.1.0",
  "id": "msg_001",
  "kind": "command",
  "request_id": null,
  "run_id": null,
  "timestamp": "2026-04-03T00:00:00Z",
  "payload": {}
}
```

## Kinds

- `command`
- `ack`
- `ready`
- `heartbeat`
- `progress`
- `status`
- `log`
- `result`
- `error`
- `backend_error`
- `cancelled`

## Initial Commands

- `health_check`
- `list_sheets`
- `inspect_input`
- `analyze_template`
- `validate_run`
- `execute_run`
- `cancel_run`

## Transport Rules

- Newline-delimited JSON only.
- No workbook, DataFrame, or other live Python object crosses the wire.
- Large artifacts are written to disk and returned as file paths plus metadata.
- `request_id` correlates non-run commands.
- `run_id` correlates long-running executions and cancellation.

## Current Command Payloads

- `health_check`
  - request body: `{ "app": "reliability_tools_desktop" }`
  - result payload: backend identity and protocol version
- `list_sheets`
  - request body: `{ "path": "C:\\path\\to\\file.xlsx" }`
  - result payload: workbook path and sheet names
- `inspect_input`
  - request body: `{ "path": "...", "sheet": "Sheet1", "role": "bom" }`
  - result payload:
    - `path`
    - `sheet`
    - `header_row`
    - `row_count`
    - `columns`
    - `preview_rows`
- `analyze_template`
  - request body: `{ "path": "...", "sheet": "FMEA Sheet", "role": "targetWorkbook" }`
  - result payload:
    - `path`
    - `sheet`
    - `header_row`
    - `columns`
    - `merged_range_count`
    - `freeze_panes`
    - `protected_sheet`
- `validate_run`
  - request body:
    - `workflowId`
    - `outputStrategyId`
    - `enrichments`
    - `inputs`
    - `mappings`
  - result payload:
    - `ok`
    - `reason_code`
    - `toast_text`
    - `validations`
- `execute_run`
  - request body:
    - `workflowId`
    - `outputStrategyId`
    - `enrichments`
    - `inputs`
    - `mappings`
  - immediate response: `ack` (see Streamed Run Events below)
  - terminal result payload (emitted as `result` kind):
    - `status`
    - `title`
    - `summary`
    - `output_file`
    - `primary_metric`
    - `secondary_metric`
    - `notes`
    - `log_lines`
    - `row_count`
    - `warning_count`
    - `no_match_count`
- `cancel_run`
  - request body: `{ "run_id": "run_..." }`
  - result payload: `{ "accepted": true, "run_id": "...", "status": "cancelling" }`

## Streamed Run Events

`execute_run` is the only long-running command. It uses a streamed event model
instead of a single request/response. All streamed events carry a `run_id` for
correlation. The flow is:

```
command (execute_run)
  → ack                          # immediate acceptance with run_id
  → status (starting)            # run is initializing
  → status (running)             # processing has begun
  → progress (0..100)            # repeated as work advances
  → log (info/warning/error)     # repeated log lines from backend
  → status (success|cancelled|failure)  # terminal status
  → result | cancelled | backend_error  # terminal event with payload
```

### Event kinds and payloads

**`ack`** — emitted immediately when `execute_run` is accepted.
```json
{ "accepted": true, "run_id": "run_abc123", "mode": "desktop-bridge" }
```

**`status`** — phase transition during a run.
```json
{ "status": "starting|running|cancelling|success|cancelled|failure",
  "stage": "Reading input files",
  "message": "Human-readable status text" }
```

**`progress`** — progress update during a run.
```json
{ "stage": "Generating FMEA rows",
  "message": "Generating FMEA rows...",
  "percent": 42,
  "current": 210,
  "total": 500 }
```

**`log`** — single log line from the backend.
```json
{ "level": "info|warning|error|debug", "line": "Log message text" }
```

**`result`** — terminal event on successful completion. Payload matches the
`execute_run` result schema above.

**`cancelled`** — terminal event when a run is cancelled via `cancel_run`.
```json
{ "message": "Operation cancelled by user." }
```

**`backend_error`** — terminal event on unhandled backend failure.
```json
{ "message": "Error description" }
```

### Cancellation flow

1. Frontend sends `cancel_run` with the active `run_id`.
2. Sidecar responds with `result` (status `cancelling`) and sets the cancel flag.
3. The processor checks the cancellation token at regular intervals.
4. When the processor raises `CancellationError`, the sidecar emits
   `status` (cancelled) followed by a `cancelled` terminal event.

### Terminal event guarantees

Every `ack` is eventually followed by exactly one terminal event:
- `result` on success
- `cancelled` on cancellation
- `backend_error` on unhandled failure

The `ACTIVE_RUN` is cleared after the terminal event is emitted.

## Heartbeat

The sidecar emits periodic heartbeat messages on a 5-second interval. The Rust
bridge tracks the last heartbeat timestamp and triggers a disconnect if no
heartbeat is received within 15 seconds.

```json
{ "kind": "heartbeat", "payload": { "backend": "python-sidecar", "protocol_version": "0.1.0" } }
```

The heartbeat thread starts after the `ready` message and runs until stdin closes.
The Rust supervisor thread checks the heartbeat timestamp every 5 seconds and calls
`handle_disconnect()` if the heartbeat is overdue. On disconnect, the frontend
attempts automatic reconnection with exponential backoff (2s, 4s, 8s, 15s, 30s).

## Current Runtime Shape

- The desktop shell keeps a managed Python sidecar session alive across bridge commands.
- `health_check`, `list_sheets`, `inspect_input`, `analyze_template`, `validate_run`, `execute_run`, and `cancel_run` are implemented.
- Supported workflows: `piece_part_generate`, `bom_only`, `fill_gaps`.
- Supported output strategies: `new_workbook_standard`, `existing_workbook_preserve_formatting`.
- `execute_run` uses a background thread with streamed events; all other commands are synchronous request/response.
- Run-scoped events are correlated by `run_id` and routed to the frontend via Tauri event channels.
- Only one active run is allowed at a time; a second `execute_run` is rejected with an error.
- Heartbeat supervision is active: sidecar emits every 5s, Rust bridge times out at 15s.
- On disconnect, the frontend automatically attempts reconnection with backoff.
- Crash restart policy and multi-run queueing remain later work.
