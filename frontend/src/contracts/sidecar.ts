import { z } from "zod";

export const protocolVersion = "0.1.0";
export const backendModeSchema = z.enum(["browser-mock", "desktop-bridge"]);

export const messageKindSchema = z.enum([
  "command",
  "ack",
  "ready",
  "heartbeat",
  "progress",
  "status",
  "log",
  "result",
  "error",
  "backend_error",
  "cancelled",
]);

export const sidecarEnvelopeSchema = z.object({
  protocol_version: z.string(),
  id: z.string(),
  kind: messageKindSchema,
  request_id: z.string().nullable().optional(),
  run_id: z.string().nullable().optional(),
  timestamp: z.string(),
  payload: z.unknown(),
});

export const commandNameSchema = z.enum([
  "health_check",
  "list_sheets",
  "inspect_input",
  "analyze_template",
  "validate_run",
  "execute_run",
  "cancel_run",
  "read_flet_config",
]);

export const healthCheckPayloadSchema = z.object({
  app: z.literal("reliability_tools_desktop"),
});

export const listSheetsPayloadSchema = z.object({
  path: z.string(),
});

export const inspectInputPayloadSchema = z.object({
  path: z.string(),
  sheet: z.string(),
  role: z.string().optional(),
});

export const analyzeTemplatePayloadSchema = z.object({
  path: z.string(),
  sheet: z.string(),
  role: z.string().optional(),
});

export const inspectionResultSchema = z.object({
  path: z.string(),
  sheet: z.string(),
  header_row: z.number(),
  row_count: z.number(),
  columns: z.array(z.string()),
  preview_rows: z.array(z.record(z.string(), z.string())),
  rows_scanned: z.number(),
  columns_scanned: z.number(),
  row_cap_applied: z.boolean(),
  column_cap_applied: z.boolean(),
  header_search_cap_applied: z.boolean(),
  mode: backendModeSchema,
});

export const templateAnalysisResultSchema = z.object({
  path: z.string(),
  sheet: z.string(),
  header_row: z.number(),
  columns: z.array(z.string()),
  merged_range_count: z.number(),
  freeze_panes: z.string().nullable(),
  protected_sheet: z.boolean(),
  rows_scanned: z.number(),
  columns_scanned: z.number(),
  row_cap_applied: z.boolean(),
  column_cap_applied: z.boolean(),
  header_search_cap_applied: z.boolean(),
  mode: backendModeSchema,
});

export const validationMessageSchema = z.object({
  id: z.string(),
  severity: z.enum(["info", "warning", "error"]),
  area: z.string(),
  title: z.string(),
  detail: z.string(),
});

export const validateRunResultSchema = z.object({
  ok: z.boolean(),
  reason_code: z.string(),
  toast_text: z.string(),
  validations: z.array(validationMessageSchema),
  mode: backendModeSchema,
});

export const executeRunAcceptedResultSchema = z.object({
  run_id: z.string(),
  mode: backendModeSchema,
  session_generation: z.number().int().nonnegative(),
});

export const cancelRunResultSchema = z.object({
  accepted: z.boolean(),
  run_id: z.string(),
  status: z.literal("cancelling"),
  mode: backendModeSchema,
});

export const runStatusValueSchema = z.enum([
  "starting",
  "running",
  "cancelling",
  "success",
  "failure",
  "cancelled",
]);

export const runStatusPayloadSchema = z.object({
  status: runStatusValueSchema,
  stage: z.string(),
  message: z.string(),
});

export const runProgressPayloadSchema = z.object({
  stage: z.string(),
  message: z.string(),
  percent: z.number(),
  current: z.number().nullable().optional(),
  total: z.number().nullable().optional(),
});

export const runLogPayloadSchema = z.object({
  level: z.enum(["debug", "info", "warning", "error"]),
  line: z.string(),
});

export const runBackendErrorPayloadSchema = z.object({
  message: z.string(),
  // Optional fields added in 0.2.2: a stable error code (typically the
  // exception type name) and the full Python traceback for debugging.
  code: z.string().optional(),
  traceback: z.string().optional(),
});

export const runCancelledPayloadSchema = z.object({
  message: z.string(),
});

const runEnvelopeBaseSchema = sidecarEnvelopeSchema.extend({
  run_id: z.string(),
});

export const runAckEnvelopeSchema = runEnvelopeBaseSchema.extend({
  kind: z.literal("ack"),
  payload: executeRunAcceptedResultSchema.extend({
    accepted: z.boolean().optional(),
  }),
});

export const runStatusEnvelopeSchema = runEnvelopeBaseSchema.extend({
  kind: z.literal("status"),
  payload: runStatusPayloadSchema,
});

export const runProgressEnvelopeSchema = runEnvelopeBaseSchema.extend({
  kind: z.literal("progress"),
  payload: runProgressPayloadSchema,
});

export const runLogEnvelopeSchema = runEnvelopeBaseSchema.extend({
  kind: z.literal("log"),
  payload: runLogPayloadSchema,
});

export const runResultEnvelopeSchema = runEnvelopeBaseSchema.extend({
  kind: z.literal("result"),
  payload: z.unknown(),
});

export const runBackendErrorEnvelopeSchema = runEnvelopeBaseSchema.extend({
  kind: z.literal("backend_error"),
  payload: runBackendErrorPayloadSchema,
});

export const runCancelledEnvelopeSchema = runEnvelopeBaseSchema.extend({
  kind: z.literal("cancelled"),
  payload: runCancelledPayloadSchema,
});

export const sidecarRunEventSchema = z.discriminatedUnion("kind", [
  runAckEnvelopeSchema,
  runStatusEnvelopeSchema,
  runProgressEnvelopeSchema,
  runLogEnvelopeSchema,
  runResultEnvelopeSchema,
  runBackendErrorEnvelopeSchema,
  runCancelledEnvelopeSchema,
]);

export const backendSessionEventSchema = z.object({
  kind: z.enum(["connected", "disconnected"]),
  connected: z.boolean(),
  backend: z.string(),
  message: z.string(),
});

export const backendSessionStatusResultSchema = z.object({
  connected: z.boolean(),
  backend: z.string(),
  mode: backendModeSchema,
  session_generation: z.number().int().nonnegative(),
});

export type BackendSessionStatusResult = z.infer<typeof backendSessionStatusResultSchema>;

export const executeRunResultSchema = z.object({
  status: z.enum(["success", "failure"]),
  title: z.string(),
  summary: z.string(),
  output_file: z.string(),
  primary_metric: z.string(),
  secondary_metric: z.string(),
  notes: z.array(z.string()),
  log_lines: z.array(z.string()),
  row_count: z.number(),
  warning_count: z.number(),
  no_match_count: z.number(),
  mode: backendModeSchema,
});

export const sidecarCommandSchema = sidecarEnvelopeSchema.extend({
  kind: z.literal("command"),
  payload: z.object({
    command: commandNameSchema,
    body: z.record(z.string(), z.unknown()),
  }),
});

export type SidecarEnvelope = z.infer<typeof sidecarEnvelopeSchema>;
export type SidecarCommand = z.infer<typeof sidecarCommandSchema>;
export type InspectionResult = z.infer<typeof inspectionResultSchema>;
export type TemplateAnalysisResult = z.infer<typeof templateAnalysisResultSchema>;
export type ValidationMessageResult = z.infer<typeof validationMessageSchema>;
export type ValidateRunResult = z.infer<typeof validateRunResultSchema>;
export type ExecuteRunAcceptedResult = z.infer<typeof executeRunAcceptedResultSchema>;
export type CancelRunResult = z.infer<typeof cancelRunResultSchema>;
export type SidecarRunEvent = z.infer<typeof sidecarRunEventSchema>;
export type BackendSessionEvent = z.infer<typeof backendSessionEventSchema>;
export type ExecuteRunResult = z.infer<typeof executeRunResultSchema>;
