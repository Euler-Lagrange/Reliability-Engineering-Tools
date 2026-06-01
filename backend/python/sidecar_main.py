from __future__ import annotations

import json
import logging
import os
import sys
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - covered in runtime environments with deps
    load_workbook = None

from common.cancellation import CancellationError
from common.utils import ensure_file_available
from common.logger import get_log_directory, write_crash_dump
from fmea.runtime import execute_run_request as fmea_execute, validate_run_request as fmea_validate
from bom_compare.runtime import execute_run_request as bom_execute, validate_run_request as bom_validate
from failure_rate.runtime import execute_run_request as fr_execute, validate_run_request as fr_validate
from refdes_extractor.runtime import execute_run_request as refdes_execute, validate_run_request as refdes_validate

FMEA_WORKFLOWS = {"piece_part_generate", "bom_only", "fill_gaps", "functional_to_piecepart"}
BOM_COMPARE_WORKFLOWS = {"bom_compare_group", "bom_compare_custom"}
FAILURE_RATE_WORKFLOWS = {"failure_rate_link"}
REFDES_WORKFLOWS = {"refdes_extract"}


def route_validate(body: dict) -> dict:
    wf = str(body.get("workflowId", "")).strip()
    if wf in BOM_COMPARE_WORKFLOWS:
        return bom_validate(body)
    if wf in FAILURE_RATE_WORKFLOWS:
        return fr_validate(body)
    if wf in REFDES_WORKFLOWS:
        return refdes_validate(body)
    return fmea_validate(body)


def route_execute(body: dict, **kwargs) -> dict:
    wf = str(body.get("workflowId", "")).strip()
    if wf in BOM_COMPARE_WORKFLOWS:
        return bom_execute(body, **kwargs)
    if wf in FAILURE_RATE_WORKFLOWS:
        return fr_execute(body, **kwargs)
    if wf in REFDES_WORKFLOWS:
        return refdes_execute(body, **kwargs)
    return fmea_execute(body, **kwargs)


PROTOCOL_VERSION = "0.1.0"
EMIT_LOCK = threading.Lock()
ACTIVE_RUN_LOCK = threading.Lock()
ACTIVE_RUN: "ActiveRun | None" = None
MAX_INSPECTION_COLUMNS = 100
MAX_INSPECTION_DATA_ROWS = 20_000
MAX_HEADER_SEARCH_ROWS = 1_000


@dataclass
class Envelope:
    kind: str
    payload: dict[str, Any]
    request_id: str | None = None
    run_id: str | None = None

    def to_json(self) -> str:
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "id": f"msg_{uuid.uuid4().hex[:12]}",
            "kind": self.kind,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": self.payload,
        }
        return json.dumps(body, ensure_ascii=True)


@dataclass
class ActiveRun:
    run_id: str
    request_id: str | None
    processor: Any | None = None
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bind_processor(self, processor: Any) -> None:
        with self.lock:
            self.processor = processor
            if self.cancel_requested.is_set():
                processor.cancel.cancel()

    def request_cancel(self) -> None:
        with self.lock:
            self.cancel_requested.set()
            if self.processor is not None:
                self.processor.cancel.cancel()


def emit(kind: str, payload: dict[str, Any], request_id: str | None = None, run_id: str | None = None) -> None:
    with EMIT_LOCK:
        sys.stdout.write(Envelope(kind=kind, payload=payload, request_id=request_id, run_id=run_id).to_json())
        sys.stdout.write("\n")
        sys.stdout.flush()


def _normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _select_sheet(workbook: Any, requested_sheet: str | None) -> Any:
    if requested_sheet and requested_sheet in workbook.sheetnames:
        return workbook[requested_sheet]
    return workbook[workbook.sheetnames[0]]


def _worksheet_column_bound(worksheet: Any) -> tuple[int, bool]:
    max_column = getattr(worksheet, "max_column", None)
    if isinstance(max_column, int) and max_column > 0:
        return min(max_column, MAX_INSPECTION_COLUMNS), max_column > MAX_INSPECTION_COLUMNS
    return MAX_INSPECTION_COLUMNS, False


def _finalize_headers(normalized_row: list[str]) -> list[str]:
    last_non_empty_index = -1
    for index, value in enumerate(normalized_row):
        if value:
            last_non_empty_index = index

    if last_non_empty_index == -1:
        return []

    return [
        value or f"Column {index + 1}"
        for index, value in enumerate(normalized_row[: last_non_empty_index + 1])
    ]


def _extract_header_details(worksheet: Any) -> tuple[int, list[str], int, int, bool, bool]:
    header_row_index = 0
    header_rows_scanned = 0
    inspected_columns, column_cap_applied = _worksheet_column_bound(worksheet)

    for row_index, row in enumerate(
        worksheet.iter_rows(values_only=True, max_col=MAX_INSPECTION_COLUMNS),
        start=1,
    ):
        header_rows_scanned += 1
        normalized_row = [_normalize_cell(value) for value in row]
        headers = _finalize_headers(normalized_row)
        if headers:
            return (
                row_index,
                headers,
                header_rows_scanned,
                min(len(headers), inspected_columns),
                column_cap_applied,
                False,
            )
        if header_rows_scanned >= MAX_HEADER_SEARCH_ROWS:
            break

    raise ValueError(
        "Could not locate a non-empty header row within the first "
        f"{MAX_HEADER_SEARCH_ROWS} scanned rows of the selected worksheet."
    )


def _extract_header_and_rows(
    worksheet: Any,
) -> tuple[int, list[str], list[dict[str, str]], int, dict[str, Any]]:
    (
        header_row_index,
        headers,
        header_rows_scanned,
        inspected_columns,
        column_cap_applied,
        header_search_cap_applied,
    ) = _extract_header_details(worksheet)
    preview_rows: list[dict[str, str]] = []
    data_row_count = 0
    rows_scanned = 0
    row_cap_applied = False

    for row in worksheet.iter_rows(
        values_only=True,
        min_row=header_row_index + 1,
        max_col=MAX_INSPECTION_COLUMNS,
    ):
        rows_scanned += 1
        normalized_row = [_normalize_cell(value) for value in row[: len(headers)]]
        row_payload = {
            header: value
            for header, value in zip(headers, normalized_row)
            if header and value
        }
        if rows_scanned >= MAX_INSPECTION_DATA_ROWS:
            row_cap_applied = True
            if not row_payload:
                break

        if not row_payload:
            continue

        data_row_count += 1
        if len(preview_rows) < 3:
            preview_rows.append(row_payload)
        if row_cap_applied:
            break

    return (
        header_row_index,
        headers,
        preview_rows,
        data_row_count,
        {
            "rows_scanned": rows_scanned,
            "columns_scanned": inspected_columns,
            "row_cap_applied": row_cap_applied,
            "column_cap_applied": column_cap_applied,
            "header_search_cap_applied": header_search_cap_applied,
            "header_rows_scanned": header_rows_scanned,
        },
    )


def inspect_input(path: Path, requested_sheet: str | None) -> dict[str, Any]:
    if load_workbook is None:
        raise RuntimeError("openpyxl is not available")

    # Parity with list_sheets: hydrate OneDrive "cloud-only" placeholders before
    # opening, so inspection doesn't fail where the real run would hydrate-and-read.
    path = ensure_file_available(path)
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = _select_sheet(workbook, requested_sheet)
        header_row_index, headers, preview_rows, data_row_count, scan_meta = _extract_header_and_rows(
            worksheet
        )
        return {
            "path": str(path),
            "sheet": worksheet.title,
            "header_row": header_row_index,
            "row_count": data_row_count,
            "columns": headers,
            "preview_rows": preview_rows,
            "rows_scanned": scan_meta["rows_scanned"],
            "columns_scanned": scan_meta["columns_scanned"],
            "header_rows_scanned": scan_meta["header_rows_scanned"],
            "row_cap_applied": scan_meta["row_cap_applied"],
            "column_cap_applied": scan_meta["column_cap_applied"],
            "header_search_cap_applied": scan_meta["header_search_cap_applied"],
        }
    finally:
        workbook.close()


def analyze_template(path: Path, requested_sheet: str | None) -> dict[str, Any]:
    if load_workbook is None:
        raise RuntimeError("openpyxl is not available")

    # Parity with list_sheets: hydrate OneDrive "cloud-only" placeholders before
    # opening, so template analysis doesn't fail where the real run would.
    path = ensure_file_available(path)
    workbook = load_workbook(path, read_only=False, data_only=False)
    try:
        worksheet = _select_sheet(workbook, requested_sheet)
        (
            header_row_index,
            headers,
            header_rows_scanned,
            inspected_columns,
            column_cap_applied,
            header_search_cap_applied,
        ) = _extract_header_details(worksheet)
        freeze_panes = worksheet.freeze_panes
        return {
            "path": str(path),
            "sheet": worksheet.title,
            "header_row": header_row_index,
            "columns": headers,
            "merged_range_count": len(worksheet.merged_cells.ranges),
            "freeze_panes": str(freeze_panes) if freeze_panes is not None else None,
            "protected_sheet": bool(getattr(worksheet.protection, "sheet", False)),
            "rows_scanned": 0,
            "columns_scanned": inspected_columns,
            "row_cap_applied": False,
            "column_cap_applied": column_cap_applied,
            "header_search_cap_applied": header_search_cap_applied,
            "header_rows_scanned": header_rows_scanned,
        }
    finally:
        workbook.close()


def _active_run() -> ActiveRun | None:
    with ACTIVE_RUN_LOCK:
        return ACTIVE_RUN


def _set_active_run(run: ActiveRun) -> None:
    global ACTIVE_RUN
    with ACTIVE_RUN_LOCK:
        ACTIVE_RUN = run


def _clear_active_run(run_id: str) -> None:
    global ACTIVE_RUN
    with ACTIVE_RUN_LOCK:
        if ACTIVE_RUN and ACTIVE_RUN.run_id == run_id:
            ACTIVE_RUN = None


def _parse_log_level(message: str) -> str:
    upper = message.upper()
    if " ERROR:" in upper:
        return "error"
    if " WARNING:" in upper:
        return "warning"
    if " DEBUG:" in upper:
        return "debug"
    return "info"


def _emit_run_status(run_id: str, status: str, stage: str, message: str) -> None:
    emit(
        "status",
        {
            "status": status,
            "stage": stage,
            "message": message,
        },
        run_id=run_id,
    )


def _emit_run_progress(
    run_id: str,
    stage: str,
    message: str,
    percent: int,
    current: int | None = None,
    total: int | None = None,
) -> None:
    emit(
        "progress",
        {
            "stage": stage,
            "message": message,
            "percent": percent,
            "current": current,
            "total": total,
        },
        run_id=run_id,
    )


def _emit_run_log(run_id: str, message: str) -> None:
    emit(
        "log",
        {
            "level": _parse_log_level(message),
            "line": message,
        },
        run_id=run_id,
    )


def _run_in_background(run: ActiveRun, body: dict[str, Any]) -> None:
    try:
        result = route_execute(
            body,
            log_callback=lambda message: _emit_run_log(run.run_id, message),
            status_callback=lambda status, stage, message: _emit_run_status(run.run_id, status, stage, message),
            progress_callback=lambda stage, message, percent, current, total: _emit_run_progress(
                run.run_id,
                stage,
                message,
                percent,
                current,
                total,
            ),
            processor_ready_callback=run.bind_processor,
        )
        _emit_run_status(run.run_id, "success", "Complete", "Run completed successfully.")
        emit("result", result, run_id=run.run_id)
    except CancellationError as exc:
        message = str(exc) or "Operation cancelled by user."
        _emit_run_status(run.run_id, "cancelled", "Cancelled", message)
        emit("cancelled", {"message": message}, run_id=run.run_id)
    except Exception as exc:  # pragma: no cover - exercised in integration runtime
        # Capture the full traceback so the UI and the file log both have
        # actionable diagnostics. The shared file logger writes to
        # ``~/.reliability_tools/logs/`` for post-mortem; the streamed
        # ``backend_error`` envelope carries the same info to the frontend
        # so the user can copy/paste it without leaving the app.
        tb = traceback.format_exc()
        message = str(exc) or "Unknown backend execution failure."
        error_code = type(exc).__name__
        # Stream the traceback into the run log so it's visible in the UI
        # panel even when the user doesn't open the error block.
        for line in tb.splitlines():
            _emit_run_log(run.run_id, line)
        try:
            logging.getLogger("reliability_tools.sidecar").exception(
                "Run %s failed with %s", run.run_id, error_code
            )
        except Exception:  # pragma: no cover - logging must never crash the run
            pass
        _emit_run_status(run.run_id, "failure", "Run failed", message)
        emit(
            "backend_error",
            {"message": message, "code": error_code, "traceback": tb},
            run_id=run.run_id,
        )
    finally:
        _clear_active_run(run.run_id)


FLET_CONFIG_NAMESPACES = [
    "bom_compare",
    "failure_rate",
    "fmea_generator",
    "refdes_extractor",
    "refdes_extractor_darkstar",
    "refdes_test",
    "reliability_tools_global",
]


def _read_flet_config(body: dict[str, Any]) -> dict[str, Any]:
    """Read Flet-era config files (read-only, never mutates)."""
    home = Path.home()
    namespace = str(body.get("namespace", "")).strip()

    if namespace:
        namespaces = [namespace] if namespace in FLET_CONFIG_NAMESPACES else []
    else:
        namespaces = FLET_CONFIG_NAMESPACES

    configs: dict[str, Any] = {}
    for ns in namespaces:
        config_path = home / f".{ns}_config.json"
        if config_path.exists():
            try:
                configs[ns] = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                configs[ns] = None
        else:
            configs[ns] = None

    return {
        "configs": configs,
        "namespaces": namespaces,
        "home": str(home),
    }


def handle_command(message: dict[str, Any]) -> None:
    request_id = message.get("request_id")
    payload = message.get("payload", {})
    command = payload.get("command")
    body = payload.get("body", {})

    if command == "health_check":
        try:
            log_dir_value = str(get_log_directory())
        except Exception:  # pragma: no cover - defensive
            log_dir_value = None
        emit(
            "result",
            {
                "status": "ok",
                "backend": "python-sidecar",
                "protocol_version": PROTOCOL_VERSION,
                "log_directory": log_dir_value,
            },
            request_id=request_id,
        )
        return

    if command == "list_sheets":
        if load_workbook is None:
            emit("error", {"message": "openpyxl is not available"}, request_id=request_id)
            return

        try:
            path = Path(body["path"])
            # Parity with inspect_input / analyze_template: hydrate
            # OneDrive "cloud-only" placeholders before opening so list_sheets
            # doesn't fail where the real runtime would succeed.
            resolved = ensure_file_available(path)
            workbook = load_workbook(resolved, read_only=True, data_only=True)
            try:
                emit(
                    "result",
                    {
                        "path": str(resolved),
                        "sheets": list(workbook.sheetnames),
                    },
                    request_id=request_id,
                )
            finally:
                workbook.close()
        except Exception as exc:  # pragma: no cover - exercised in integration runtime
            emit("error", {"message": str(exc)}, request_id=request_id)
        return

    if command == "inspect_input":
        path = Path(body["path"])
        sheet = body.get("sheet")
        try:
            emit("result", inspect_input(path, sheet), request_id=request_id)
        except Exception as exc:  # pragma: no cover - exercised in integration runtime
            emit("error", {"message": str(exc)}, request_id=request_id)
        return

    if command == "analyze_template":
        path = Path(body["path"])
        sheet = body.get("sheet")
        try:
            emit("result", analyze_template(path, sheet), request_id=request_id)
        except Exception as exc:  # pragma: no cover - exercised in integration runtime
            emit("error", {"message": str(exc)}, request_id=request_id)
        return

    if command == "validate_run":
        try:
            emit("result", route_validate(body), request_id=request_id)
        except Exception as exc:  # pragma: no cover - exercised in integration runtime
            emit("error", {"message": str(exc)}, request_id=request_id)
        return

    if command == "execute_run":
        if _active_run() is not None:
            emit(
                "error",
                {"message": "Another backend run is already active. Wait for it to finish or cancel it first."},
                request_id=request_id,
            )
            return

        try:
            validation = route_validate(body)
        except Exception as exc:  # pragma: no cover - exercised in integration runtime
            emit("error", {"message": str(exc)}, request_id=request_id)
            return
        if not validation["ok"]:
            emit("error", {"message": validation["toast_text"]}, request_id=request_id)
            return

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run = ActiveRun(run_id=run_id, request_id=request_id)
        _set_active_run(run)
        emit(
            "ack",
            {
                "accepted": True,
                "run_id": run_id,
                "mode": "desktop-bridge",
            },
            request_id=request_id,
            run_id=run_id,
        )
        thread = threading.Thread(target=_run_in_background, args=(run, body), daemon=True)
        thread.start()
        return

    if command == "cancel_run":
        run_id = str(body.get("run_id", "")).strip()
        active_run = _active_run()
        if not run_id:
            emit("error", {"message": "cancel_run requires a run_id."}, request_id=request_id)
            return
        if active_run is None or active_run.run_id != run_id:
            emit("error", {"message": f"No active run matches '{run_id}'."}, request_id=request_id)
            return

        active_run.request_cancel()
        _emit_run_status(
            run_id,
            "cancelling",
            "Cancellation requested",
            "Cancellation requested. Waiting for the backend to stop safely.",
        )
        emit(
            "result",
            {
                "accepted": True,
                "run_id": run_id,
                "status": "cancelling",
                "mode": "desktop-bridge",
            },
            request_id=request_id,
            run_id=run_id,
        )
        return

    if command == "read_flet_config":
        try:
            emit("result", _read_flet_config(body), request_id=request_id)
        except Exception as exc:
            emit("error", {"message": str(exc)}, request_id=request_id)
        return

    emit(
        "error",
        {
            "message": f"Command '{command}' is not implemented yet in the sidecar scaffold.",
        },
        request_id=request_id,
    )


HEARTBEAT_INTERVAL = float(os.environ.get("SIDECAR_HEARTBEAT_INTERVAL", "5.0"))


def _heartbeat_loop(stop_event: threading.Event) -> None:
    """Emit periodic heartbeat messages until stop_event is set."""
    while not stop_event.wait(HEARTBEAT_INTERVAL):
        emit(
            "heartbeat",
            {
                "backend": "python-sidecar",
                "protocol_version": PROTOCOL_VERSION,
            },
        )


def iter_messages() -> None:
    emit(
        "ready",
        {
            "backend": "python-sidecar",
            "protocol_version": PROTOCOL_VERSION,
        },
    )

    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, args=(heartbeat_stop,), daemon=True,
    )
    heartbeat_thread.start()

    try:
        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                message = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                # Malformed envelope — surface as a generic error so the
                # bridge can log it; do not kill the sidecar.
                emit("error", {"message": f"Malformed sidecar envelope: {exc}"})
                continue
            if message.get("kind") != "command":
                continue
            try:
                handle_command(message)
            except Exception as exc:  # pragma: no cover - defense in depth
                # Last-resort guard: any exception that escapes a command
                # branch becomes a generic error envelope tied to the
                # request_id (if available) so the sidecar keeps serving
                # subsequent commands instead of dying.
                request_id = message.get("request_id") if isinstance(message, dict) else None
                emit(
                    "error",
                    {
                        "message": (
                            f"Unhandled sidecar exception while running command: {exc}"
                        ),
                        "exception_type": type(exc).__name__,
                    },
                    request_id=request_id,
                )
    finally:
        heartbeat_stop.set()


def _install_crash_hooks() -> None:
    """Install ``sys.excepthook`` and ``threading.excepthook`` so any
    unhandled exception in the sidecar process (main thread OR background
    threads) is captured as a crash dump under ``<log_dir>/crashes/``.

    The default Python behaviour is to print the traceback to stderr and
    exit — that still happens, but users get a shareable file too. We also
    emit a last-gasp ``log`` event on stdout so the Rust bridge surfaces a
    notification before the sidecar process dies.
    """

    def _sidecar_excepthook(exc_type, exc_value, exc_tb) -> None:
        # Preserve normal behaviour for KeyboardInterrupt so Ctrl+C still
        # exits cleanly under developer shells.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        dump_path = write_crash_dump("sidecar", exc_type, exc_value, exc_tb)
        try:
            detail = f"Unhandled exception: {exc_type.__name__}: {exc_value}"
            if dump_path is not None:
                detail = f"{detail} (see {dump_path})"
            emit("log", {"level": "error", "line": detail})
        except Exception:  # noqa: BLE001 — never fail inside the excepthook
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        dump_path = write_crash_dump(
            "thread",
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            thread_name=args.thread.name if args.thread else None,
        )
        try:
            detail = (
                f"Unhandled thread exception in "
                f"{args.thread.name if args.thread else '<unknown>'}: "
                f"{args.exc_type.__name__}: {args.exc_value}"
            )
            if dump_path is not None:
                detail = f"{detail} (see {dump_path})"
            emit("log", {"level": "error", "line": detail})
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = _sidecar_excepthook
    threading.excepthook = _thread_excepthook


def main() -> int:
    _install_crash_hooks()

    if "--self-test" in sys.argv:
        from common.security_audit import audit_tree

        audit_root = Path(__file__).resolve().parent
        violations = audit_tree(audit_root)
        if violations:
            print(f"SELF-TEST FAIL: {len(violations)} security violation(s):")
            for violation in violations:
                print(f"  {violation.format(root=audit_root)}")
            return 1
        print("SELF-TEST OK: python-sidecar 0.1.0 (security_audit: clean)")
        return 0

    iter_messages()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
