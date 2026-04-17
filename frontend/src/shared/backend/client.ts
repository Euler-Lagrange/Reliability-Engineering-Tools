import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { z } from "zod";
import {
  analyzeTemplatePayloadSchema,
  backendModeSchema,
  backendSessionEventSchema,
  backendSessionStatusResultSchema,
  cancelRunResultSchema,
  executeRunAcceptedResultSchema,
  fletConfigResultSchema,
  inspectionResultSchema,
  protocolVersion,
  sidecarRunEventSchema,
  templateAnalysisResultSchema,
  validateRunResultSchema,
} from "../../contracts/sidecar";
import type {
  BackendSessionEvent,
  BackendSessionStatusResult,
  CancelRunResult,
  ExecuteRunAcceptedResult,
  FletConfigResult,
  SidecarRunEvent,
} from "../../contracts/sidecar";
import type { BackendMode } from "../../stores/shellStore";

const BACKEND_RUN_EVENT = "backend://run-event";
const BACKEND_SESSION_EVENT = "backend://session";

// Tracks in-flight cancelRun requests keyed by runId so double-dispatch
// (e.g. rapid user clicks, redundant tool paths) share a single promise.
const inflightCancels = new Map<string, Promise<CancelRunResult>>();

const backendHealthResultSchema = z.object({
  status: z.literal("ok"),
  backend: z.string(),
  protocol_version: z.string(),
  mode: backendModeSchema,
  // Absolute path to the sidecar log directory. Optional because older
  // sidecars did not emit this field; Settings > Logs falls back to the
  // placeholder when it is missing.
  log_directory: z.string().nullish(),
});

const listSheetsResultSchema = z.object({
  path: z.string(),
  sheets: z.array(z.string()),
  mode: backendModeSchema,
});

export type BackendHealthResult = z.infer<typeof backendHealthResultSchema>;
export type ListSheetsResult = z.infer<typeof listSheetsResultSchema>;
export type InspectInputResult = z.infer<typeof inspectionResultSchema>;
export type AnalyzeTemplateResult = z.infer<typeof templateAnalysisResultSchema>;
export type ValidateRunResult = z.infer<typeof validateRunResultSchema>;

export interface RunRequestInput {
  role: string;
  label: string;
  path: string;
  selectedSheet: string;
  source?: "mock" | "desktop-bridge";
  isResolvingSheets?: boolean;
  isAnalyzing?: boolean;
  resolutionError?: string | null;
  sheets?: Array<{ id: string; label: string }>;
}

export interface RunRequestMapping {
  canonical: string;
  mappedTo: string;
  status: string;
}

export interface RunRequestBody {
  workflowId: string;
  outputStrategyId: string;
  inputs: RunRequestInput[];
  mappings: RunRequestMapping[];
  options?: Record<string, unknown>;
  /**
   * Absolute path to the folder where the generated output file should be
   * written. When null/undefined, the backend falls back to the "first input
   * file parent" heuristic. Phase 3 plumbs this from the FMEA Workflow card
   * output folder picker; Phase 4 wires the backend consumer.
   */
  outputDirectory?: string | null;
}

function isTauriRuntime() {
  return typeof window !== "undefined" && ("__TAURI_INTERNALS__" in window || "__TAURI__" in window);
}

async function openExcelFileInDesktop() {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selection = await open({
    title: "Select workbook",
    filters: [{ name: "Excel Workbooks", extensions: ["xlsx", "xlsm", "xls"] }],
    multiple: false,
    directory: false,
  });

  if (!selection || Array.isArray(selection)) {
    return null;
  }

  return selection;
}

async function openPdfFileInDesktop() {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selection = await open({
    title: "Select PDF schematic",
    filters: [{ name: "PDF Documents", extensions: ["pdf"] }],
    multiple: false,
    directory: false,
  });
  if (!selection || Array.isArray(selection)) {
    return null;
  }
  return selection;
}

async function openDirectoryInDesktop(defaultPath?: string) {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selection = await open({
    title: "Select output folder",
    directory: true,
    multiple: false,
    defaultPath: defaultPath || undefined,
  });

  if (!selection || Array.isArray(selection)) {
    return null;
  }

  return selection;
}

function browserHealthCheck(): Promise<BackendHealthResult> {
  return Promise.resolve({
    status: "ok",
    backend: "browser-preview",
    protocol_version: protocolVersion,
    mode: "browser-mock",
  });
}

function ensureDesktopRuntime(action: string): asserts action is string {
  if (!isTauriRuntime()) {
    throw new Error(`Desktop-only backend action unavailable in browser preview: ${action}.`);
  }
}

export type { FletConfigResult };

export interface BackendClient {
  runtimeMode: BackendMode;
  healthCheck: () => Promise<BackendHealthResult>;
  sessionStatus: () => Promise<BackendSessionStatusResult>;
  listSheets: (path: string) => Promise<ListSheetsResult>;
  inspectInput: (path: string, sheet: string, role?: string) => Promise<InspectInputResult>;
  analyzeTemplate: (path: string, sheet: string, role?: string) => Promise<AnalyzeTemplateResult>;
  validateRun: (body: RunRequestBody) => Promise<ValidateRunResult>;
  executeRun: (body: RunRequestBody) => Promise<ExecuteRunAcceptedResult>;
  cancelRun: (runId: string) => Promise<CancelRunResult>;
  readFletConfig: (namespace?: string) => Promise<FletConfigResult>;
  subscribeToRunEvents: (handler: (event: SidecarRunEvent) => void) => Promise<() => void>;
  subscribeToSessionEvents: (handler: (event: BackendSessionEvent) => void) => Promise<() => void>;
  openExcelFile: () => Promise<string | null>;
  openPdfFile: () => Promise<string | null>;
  openDirectory: (defaultPath?: string) => Promise<string | null>;
  /**
   * Open ``path`` in the host OS file manager (Explorer / Finder / xdg-open).
   * Rejects with an ``Error`` when the path does not exist or the spawn
   * fails. In browser-mock mode this throws so callers can surface the
   * "desktop required" notification themselves.
   */
  revealInFileManager: (path: string) => Promise<void>;
}

export const backendClient: BackendClient = {
  runtimeMode: isTauriRuntime() ? "desktop-bridge" : "browser-mock",
  async healthCheck() {
    if (!isTauriRuntime()) {
      return browserHealthCheck();
    }

    const result = await invoke("backend_health_check");
    const parsed = backendHealthResultSchema.parse(result);
    // Protocol-version handshake: log a warning when the sidecar speaks a
    // different version than the frontend expects. We don't hard-fail
    // because the current protocol evolves additively (new optional
    // fields), but mismatches frequently explain "why does schema X not
    // parse?" bug reports.
    if (parsed.protocol_version !== protocolVersion) {
      // eslint-disable-next-line no-console
      console.warn(
        `[backend] Protocol version mismatch: frontend=${protocolVersion}, sidecar=${parsed.protocol_version}. ` +
          `Continuing, but some fields may be missing or unexpected.`,
      );
    }
    return parsed;
  },
  async sessionStatus() {
    if (!isTauriRuntime()) {
      return {
        connected: true,
        backend: "browser-preview",
        mode: "browser-mock" as const,
        session_generation: 0,
      };
    }
    const result = await invoke("backend_session_status");
    return backendSessionStatusResultSchema.parse(result);
  },
  async listSheets(path) {
    ensureDesktopRuntime("list_sheets");
    const result = await invoke("backend_list_sheets", { path });
    return listSheetsResultSchema.parse(result);
  },
  async inspectInput(path, sheet, role) {
    ensureDesktopRuntime("inspect_input");
    const result = await invoke("backend_inspect_input", { path, sheet, role });
    return inspectionResultSchema.parse(result);
  },
  async analyzeTemplate(path, sheet, role) {
    ensureDesktopRuntime("analyze_template");
    analyzeTemplatePayloadSchema.parse({ path, sheet, role });
    const result = await invoke("backend_analyze_template", { path, sheet, role });
    return templateAnalysisResultSchema.parse(result);
  },
  async validateRun(body) {
    ensureDesktopRuntime("validate_run");
    const result = await invoke("backend_validate_run", { body });
    return validateRunResultSchema.parse(result);
  },
  async executeRun(body) {
    ensureDesktopRuntime("execute_run");
    const result = await invoke("backend_execute_run", { body });
    return executeRunAcceptedResultSchema.parse(result);
  },
  async cancelRun(runId) {
    ensureDesktopRuntime("cancel_run");
    // Dedup concurrent cancel dispatches for the same runId. Without this
    // a user double-clicking the HoldButton (or a tool calling cancel
    // from multiple paths) could queue duplicate cancels, stacking
    // notifications and confusing the UI. The first in-flight promise
    // wins and subsequent callers share its result.
    const existing = inflightCancels.get(runId);
    if (existing) return existing;
    const promise = (async () => {
      try {
        const result = await invoke("backend_cancel_run", { runId });
        return cancelRunResultSchema.parse(result);
      } finally {
        inflightCancels.delete(runId);
      }
    })();
    inflightCancels.set(runId, promise);
    return promise;
  },
  async readFletConfig(namespace?) {
    ensureDesktopRuntime("read_flet_config");
    const result = await invoke("backend_read_flet_config", { namespace: namespace ?? null });
    return fletConfigResultSchema.parse(result);
  },
  async subscribeToRunEvents(handler) {
    ensureDesktopRuntime("subscribe_run_events");
    return listen(BACKEND_RUN_EVENT, (event) => {
      handler(sidecarRunEventSchema.parse(event.payload));
    });
  },
  async subscribeToSessionEvents(handler) {
    ensureDesktopRuntime("subscribe_session_events");
    return listen(BACKEND_SESSION_EVENT, (event) => {
      handler(backendSessionEventSchema.parse(event.payload));
    });
  },
  async openExcelFile() {
    if (!isTauriRuntime()) {
      return null;
    }

    return openExcelFileInDesktop();
  },
  async openPdfFile() {
    if (!isTauriRuntime()) {
      return null;
    }

    return openPdfFileInDesktop();
  },
  async openDirectory(defaultPath) {
    if (!isTauriRuntime()) {
      return null;
    }

    return openDirectoryInDesktop(defaultPath);
  },
  async revealInFileManager(path) {
    if (!isTauriRuntime()) {
      throw new Error(
        "Revealing a path in the OS file manager requires the Tauri desktop shell.",
      );
    }
    await invoke("reveal_in_file_manager", { path });
  },
};
