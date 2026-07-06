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

## Commands

All ten commands currently implemented by the sidecar:

- `health_check`
- `list_sheets`
- `inspect_input`
- `analyze_template`
- `validate_run`
- `execute_run`
- `cancel_run`
- `read_flet_config`
- `read_refdes_prefixes`
- `write_refdes_prefixes`

## Transport Rules

- Newline-delimited JSON only.
- No workbook, DataFrame, or other live Python object crosses the wire.
- Large artifacts are written to disk and returned as file paths plus metadata.
- `request_id` correlates non-run commands.
- `run_id` correlates long-running executions and cancellation.

## Current Command Payloads

- `health_check`
  - request body: `{ "app": "reliability_tools_desktop" }`
  - result payload:
    - `status` — always `"ok"` when the sidecar is healthy (required by the frontend schema)
    - `backend` — backend identity string (e.g. `"python-sidecar"`)
    - `protocol_version` — NDJSON protocol version
    - `mode` — `"desktop-bridge"` (filled in by the Rust layer; the same
      injection applies to the `list_sheets`, `inspect_input`, and
      `analyze_template` result payloads, which is why the frontend Zod
      schemas require `mode` even though the Python sidecar does not emit
      it for those commands. `validate_run` and `execute_run` are the
      exception: their `mode` is emitted by the Python tool runtimes
      themselves and passed through raw — do not remove it there.)
    - `log_directory` (added in 0.4.2, optional) — absolute path to the
      sidecar log directory (`~/.reliability_tools/logs/` or the override
      supplied via `RELIABILITY_TOOLS_LOG_DIR`). Surfaced to the frontend
      so Settings › Logs can display the real path and reveal the folder
      via the `reveal_in_file_manager` Tauri command.
- `list_sheets`
  - request body: `{ "path": "C:\\path\\to\\file.xlsx" }`
  - result payload: workbook path and sheet names
  - As of 0.4.2 the handler calls `ensure_file_available()` before
    `openpyxl.load_workbook()`, so OneDrive cloud-only placeholders are
    hydrated on demand rather than surfacing an opaque I/O error.
- `inspect_input`
  - request body: `{ "path": "...", "sheet": "Sheet1", "role": "bom" }`
  - result payload:
    - `path`
    - `sheet`
    - `header_row`
    - `row_count`
    - `columns`
    - `preview_rows`
    - `rows_scanned` — number of physical rows the sidecar walked (bounded by
      the data-row cap); informational only
    - `columns_scanned` — number of columns inspected (bounded by the column
      cap)
    - `header_rows_scanned` — number of rows walked during header detection
      (bounded by the 1 000-row `MAX_HEADER_SEARCH_ROWS` cap); informational
    - `row_cap_applied` — `true` when the data-row cap (20 000 rows) was hit
      and later rows were not examined
    - `column_cap_applied` — `true` when the column cap (100 columns) was hit
      and later columns were not examined
    - `header_search_cap_applied` — `false` on successful `result`
      envelopes. If header detection reaches the 1 000-row cap before
      finding a non-empty header, the command returns an `error` envelope
      instead of a partial `result`.
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
    - `rows_scanned`, `columns_scanned`, `header_rows_scanned`,
      `row_cap_applied`, `column_cap_applied`, `header_search_cap_applied` —
      same sampling-cap metadata as `inspect_input`; see above
- `validate_run`
  - request body:
    - `workflowId` — routes to the tool runtime; see Workflow Routing below
    - `outputStrategyId`
    - `inputs`
    - `mappings`
    - `options` — see Run Options below
    - `outputDirectory` — string | null, optional. Absolute path to the
      folder where the generated output file should be written. When null or
      absent, the backend falls back to the input file's parent directory.
      Honored by every runtime (FMEA, BOM Compare, Failure Rate, RefDes
      Extractor) as of 0.4.2; unwritable or missing directories fall back
      to the input-parent heuristic with a warning logged via `stream_log`.
  - result payload:
    - `ok`
    - `reason_code`
    - `toast_text`
    - `validations`
    - `output_preview` — object, optional. Added in 0.4.5. A lightweight,
      best-effort sample of source/input rows mapped into review-friendly
      columns so the frontend's Review drawer can show what data the tool
      is about to work from. Omitted when validation fails, inputs are
      incomplete, or preview generation raises — preview errors never fail
      validation. Shape:
      - `columns` — string[]. Ordered column headers for the preview table.
      - `rows` — string[][]. Up to `PREVIEW_ROW_CAP` (20) rows, each a list
        of string cell values aligned with `columns`. Empty cells are
        rendered as `""`.
      - `truncated` — boolean. `true` when the full output would have more
        than `PREVIEW_ROW_CAP` rows.
      - `total_estimated` — integer. Best-effort count of the total source
        rows available for preview; used by the UI to render "showing 20 of
        1,942". `null` if the adapter cannot cheaply estimate it.
      Each runtime decides which source rows are most useful to review for
      its workflow:
      FMEA samples the BOM or functional FMEA input, BOM Compare samples the
      primary BOM, Failure Rate samples the prediction workbook, and RefDes
      Extractor samples the optional BOM workbook when provided.
- `execute_run`
  - request body:
    - `workflowId`
    - `outputStrategyId`
    - `inputs`
    - `mappings`
    - `options` — see Run Options below
    - `outputDirectory` — string | null, optional. Same semantics as
      `validate_run` above.
  - immediate response: `ack` (see Streamed Run Events below)
  - terminal result payload (emitted as `result` kind):
    - `status`
    - `title`
    - `summary`
    - `output_file`
    - `primary_metric`
    - `secondary_metric`
    - `notes` — may include a note about inherited BOM additions when the
      workbook contains a `BOM_Additions` sheet (emitted whenever pin/variant
      RefDes such as `U200-X` inherited their data from a base BOM row like
      `U200`). For `refdes_extract` runs with a BOM, the notes also carry a
      BOM-coverage summary (and a prominent BOM-cross-check-failed note when the
      BOM cannot be loaded)
    - `log_lines`
    - `row_count`
    - `warning_count`
    - `no_match_count`
    - `mode` — `"desktop-bridge"` (the runtime mode; required by the frontend schema)
- `cancel_run`
  - request body: `{ "run_id": "run_..." }`
  - result payload: `{ "accepted": true, "run_id": "...", "status": "cancelling", "mode": "desktop-bridge" }`
- `read_flet_config`
  - request body: `{ "namespace": "bom_compare" }` — optional; when omitted, all known namespaces are read
  - result payload:
    - `configs` — dict keyed by namespace, value is parsed JSON or `null`
    - `namespaces` — list of namespaces that were inspected
    - `home` — user home directory path
  - This command is read-only: the sidecar never writes or mutates the legacy Flet config files (`~/.{namespace}_config.json`). Recognized namespaces: `bom_compare`, `failure_rate`, `fmea_generator`, `refdes_extractor`, `refdes_extractor_darkstar`, `refdes_test`, `reliability_tools_global`.
- `read_refdes_prefixes`
  - request body: `{}`
  - result payload:
    - `defaults` — sorted IEEE-315 prefix list (read-only in the UI)
    - `custom` — the `ref_prefixes` array from `~/.refdes_extractor_config.json` (normalized upper-case, de-duplicated)
    - `path` — absolute path of the config file
- `write_refdes_prefixes`
  - request body: `{ "prefixes": ["PS", "XU"] }`
  - Validation: each entry must match `^[A-Z]{1,5}$` after trim/upper-case; entries duplicating an IEEE-315 default or an earlier entry are dropped silently; any invalid entry rejects the whole write (`error` envelope, file untouched).
  - Writes `ref_prefixes` into `~/.refdes_extractor_config.json` atomically (temp file + rename), preserving any other keys in the file.
  - result payload: `{ "custom": [...], "path": "...", "restart_required": true }` — `restart_required` is always true because the extraction engines freeze their prefix-derived regexes at import time; changes apply on the next app launch.

## Sampling Caps

`inspect_input` and `analyze_template` scan worksheets eagerly. To bound
worst-case memory and latency on pathological workbooks, the sidecar enforces
three caps (introduced in 0.4.1):

| Cap | Limit | Behaviour when hit |
|-----|-------|--------------------|
| Header search | First 1 000 rows | `error` envelope — no header was found within the bound |
| Column scan | First 100 columns | `column_cap_applied = true`; trailing columns are not reported |
| Data row scan | First 20 000 physical rows | `row_cap_applied = true`; trailing rows are not reported |

The header-search cap is fatal (the command cannot produce a usable header);
the column and row caps are informational — the command still returns a
`result` envelope, and the frontend surfaces a "sheet is larger than what
was scanned" warning to the user.

## Workflow Routing

`validate_run` and `execute_run` route by `workflowId` to one of four tool
runtimes. The sidecar never exposes `toolId` directly; the workflow alone
determines which backend module handles the request.

| Workflow ID | Tool runtime |
|-------------|--------------|
| `piece_part_generate` | `fmea.runtime` |
| `bom_only` | `fmea.runtime` |
| `functional_to_piecepart` | `fmea.runtime` |
| `fill_gaps` | `fmea.runtime` |
| `bom_compare_group` | `bom_compare.runtime` |
| `bom_compare_custom` | `bom_compare.runtime` |
| `extraction_compare` | `bom_compare.runtime` |
| `failure_rate_link` | `failure_rate.runtime` |
| `refdes_extract` | `refdes_extractor.runtime` |

The `functional_to_piecepart` workflow reads a functional FMEA file, detects
circuit-block rows, parses the comma-separated RefDes column (e.g.,
`Failure Mode Causes (RefDes)`) on each circuit-block row, and generates
piece-part rows beneath each block using BOM + HDA + failure modes data.
The original functional rows are preserved as-is. Required inputs:
`functionalFmea`, `bom`, `failureModes` (HDA is optional).

Unknown workflow IDs fall through to the FMEA runtime, which will reject them
via its own validation.

## Run Options

`validate_run` and `execute_run` accept an `options` object on the request
body. Currently defined fields:

- `failureModesStandard` — string, `"FMD-91"` or `"FMD-2016"`. **Required**
  for all FMEA workflows. Drives the output column headers
  (`FMD-91 Commodity Type 1/2` vs `FMD-2016 Commodity Type 1/2`) and filters
  the failure modes file by an optional `Standard` column. Missing this
  field on an FMEA workflow yields validation `reason_code`
  `"missing_failure_modes_standard"` with `toast_text`
  `"Select FMD-91 or FMD-2016 before running."`.
- `hdaSource` — string, `"inline"` or `"separate"`, FMEA workflows,
  optional. **Authoritative when present** (added in 0.4.6): `"separate"`
  with no usable `hda` input path blocks validation with `reason_code`
  `"missing_separate_hda"`; `"inline"` causes any stray `hda` input path
  to be ignored (inline detection from the BOM is used). When the field is
  absent (legacy clients), the presence of an `hda` input path decides.
- BOM Compare options (`bom_compare_group` + `bom_compare_custom`):
  `exact_match` (full canonical token matching vs base-RefDes reduction),
  `base_match` (maps to loose/prefix base matching; default off),
  `ignore_dnp` (skip Do-Not-Populate rows; the optional `dnp_regex`
  string falls back to the canonical `DEFAULT_DNP_REGEX` when omitted or
  empty — an empty pattern is never compiled), `check_fmr` (per-RefDes
  failure-mode-ratio sum validation; custom path emits a
  `Failure_Mode_Ratio` warnings sheet), and `check_part_usage`. All of
  these are honored on **both** workflows as of 0.4.6.
  `treat_prov_as_covered` is **group-only** (it keys off the grouping
  file's group-name column, which a two-BOM custom compare does not
  have); the custom path ignores it and the UI disables it there.
  `bom_compare_custom` additionally accepts `compare_columns` — an array of
  `{col_a, col_b, rule}` (rule one of `"Text (ignore case)"` / `"Text (exact)"`
  / `"Numeric"`) that drives the per-column value diff (the `Differences`
  sheet) — and `key_mode` (`"refdes_list"` default vs `"exact"`). Both are
  **custom-only**; with no `compare_columns` the custom path reports RefDes
  presence/absence only.
- Mapping values may carry the Do-Not-Map sentinel `"__do_not_map__"`
  (single source of truth: `shared/pre_run_validation.DO_NOT_MAP_SENTINEL`
  mirrored by `frontend/src/app/types.ts` `DO_NOT_MAP_VALUE`). A REQUIRED
  mapping set to the sentinel blocks validation with `reason_code`
  `"invalid_do_not_map"` — it must never reach the execute path as a
  literal column name.

The legacy `enrichments` field has been removed. The backend tolerates
legacy payloads for backward compatibility but hard-fails with
`ValidationError` if `enrichments.functional` or `enrichments.piecePart`
is truthy, to protect against stale clients. Functional FMEA is now its
own primary workflow (`functional_to_piecepart`), not an enrichment toggle.

## Error Envelope

Any synchronous command that fails emits a single `error` envelope instead of a
`result` envelope. The `request_id` echoes the original command so the frontend
can resolve the pending promise.

```json
{
  "kind": "error",
  "request_id": "req_abc123",
  "payload": {
    "message": "openpyxl is not available",
    "exception_type": "ImportError"
  }
}
```

**Payload fields:**

- `message` — required string. Human-readable error summary suitable for
  surfacing in a toast or dialog.
- `exception_type` — optional string. Set when the error comes from an
  unhandled Python exception in the top-level defense-in-depth catch inside
  `sidecar_main.py`. Contains the Python exception class name (e.g.
  `ValueError`, `KeyError`, `PermissionError`) for support-ticket triage.
  Validation errors produced by command routers may omit this field.

Run-scoped failures (raised inside the background thread after `ack`) are
surfaced as `backend_error` terminal events, not as `error` envelopes. See the
Streamed Run Events section below.

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
{ "accepted": true, "run_id": "run_abc123", "mode": "desktop-bridge",
  "session_generation": 3 }
```

`session_generation` (added in 0.4.1) is a monotonically increasing counter
that the Rust bridge increments every time it spawns a fresh sidecar
process. The Rust bridge owns this field: Python emits the raw `ack`, and
Rust enriches the streamed run event before forwarding it to the frontend.
The frontend records the value with the active run for diagnostics. On
reconnect, the frontend clears any active run because every reconnect path
spawns a fresh sidecar session and no terminal event can arrive from the
previous process.

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
{
  "message": "Error description",
  "code": "ValueError",
  "traceback": "Traceback (most recent call last):\n  File \"...\", line N, in ...\n    ...\nValueError: ..."
}
```

The `code` and `traceback` fields are optional and were added in 0.2.2.
`code` is a stable identifier (typically the Python exception type name)
that the frontend can use to map to user-facing copy. `traceback` is the
full Python stack trace formatted via `traceback.format_exc()` so
operators can copy/paste it into a bug report. Older sidecars may omit
both fields; consumers must treat them as optional.

When a run fails, the sidecar also streams every traceback line as a
`log` envelope (with `level: "error"`) before emitting `backend_error`,
so the run-log panel shows the trace inline even if the user does not
expand the error block.

### Cancellation flow

1. Frontend sends `cancel_run` with the active `run_id`.
2. Sidecar responds to the command with `result` (status `cancelling`) and
   sets the cancel flag. The Rust bridge returns this acknowledgement to the
   invoke caller; it is not forwarded as a streamed run-event `result`.
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
- Implemented commands: `health_check`, `list_sheets`, `inspect_input`, `analyze_template`, `validate_run`, `execute_run`, `cancel_run`, `read_flet_config`, `read_refdes_prefixes`, `write_refdes_prefixes`.
- Supported workflows: `piece_part_generate`, `bom_only`, `functional_to_piecepart`, `fill_gaps`, `bom_compare_group`, `bom_compare_custom`, `extraction_compare`, `failure_rate_link`, `refdes_extract`.
- Supported FMEA output strategies: `new_workbook_standard`, `existing_workbook_preserve_formatting`.
- `execute_run` uses a background thread with streamed events; all other commands are synchronous request/response.
- Run-scoped events are correlated by `run_id` and routed to the frontend via Tauri event channels.
- Only one active run is allowed at a time; a second `execute_run` is rejected with an error.
- Heartbeat supervision is active: sidecar emits every 5s, Rust bridge times out at 15s.
- On disconnect, the frontend automatically attempts reconnection with backoff.
- The Rust bridge tracks a `session_generation` counter that increments on
  every sidecar respawn. The counter is echoed on the `execute_run` ack and
  on the `backend_session_status` response. Since every reconnect spawns a
  fresh sidecar session, the frontend clears any active run after a
  successful reconnect.
- Crash restart policy and multi-run queueing remain later work.
