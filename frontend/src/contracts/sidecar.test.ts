import { describe, expect, it } from "vitest";
import {
  backendSessionEventSchema,
  fletConfigResultSchema,
  inspectionResultSchema,
  refdesPrefixesResultSchema,
  sidecarRunEventSchema,
  writeRefdesPrefixesResultSchema,
} from "./sidecar";

describe("sidecar protocol schemas", () => {
  it("preserves the Rust session generation on backend session events", () => {
    expect(
      backendSessionEventSchema.parse({
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar-session",
        message: "Desktop backend dropped.",
        session_generation: 7,
      }),
    ).toMatchObject({
      kind: "disconnected",
      session_generation: 7,
    });
  });

  it("accepts enriched run ack events emitted by the Rust bridge", () => {
    expect(
      sidecarRunEventSchema.parse({
        protocol_version: "0.1.0",
        id: "evt_ack_001",
        kind: "ack",
        request_id: "req_001",
        run_id: "run_001",
        timestamp: "2026-05-18T00:00:00Z",
        payload: {
          accepted: true,
          run_id: "run_001",
          mode: "desktop-bridge",
          session_generation: 3,
          workflow_id: "bom_compare_custom",
        },
      }),
    ).toMatchObject({
      kind: "ack",
      payload: {
        run_id: "run_001",
        session_generation: 3,
        workflow_id: "bom_compare_custom",
      },
    });
  });

  it("rejects raw Python run ack events before Rust session enrichment", () => {
    expect(() =>
      sidecarRunEventSchema.parse({
        protocol_version: "0.1.0",
        id: "evt_ack_001",
        kind: "ack",
        request_id: "req_001",
        run_id: "run_001",
        timestamp: "2026-05-18T00:00:00Z",
        payload: {
          accepted: true,
          run_id: "run_001",
          mode: "desktop-bridge",
        },
      }),
    ).toThrow();
  });

  it("accepts inspect_input header scan diagnostics", () => {
    expect(
      inspectionResultSchema.parse({
        path: "C:\\work\\input.xlsx",
        sheet: "BOM",
        header_row: 2,
        row_count: 12,
        columns: ["Reference Designator", "Part Number"],
        preview_rows: [{ "Reference Designator": "R1", "Part Number": "ABC" }],
        rows_scanned: 12,
        columns_scanned: 2,
        header_rows_scanned: 2,
        row_cap_applied: false,
        column_cap_applied: false,
        header_search_cap_applied: false,
        mode: "desktop-bridge",
      }),
    ).toMatchObject({
      header_rows_scanned: 2,
    });
  });

  it("accepts null read_flet_config namespace entries", () => {
    expect(
      fletConfigResultSchema.parse({
        configs: {
          reliability_tools_global: null,
          refdes_extractor_darkstar: {
            theme: "dark_precision",
          },
        },
        namespaces: ["reliability_tools_global", "refdes_extractor_darkstar"],
        home: "C:\\Users\\Reliability",
      }),
    ).toMatchObject({
      configs: {
        reliability_tools_global: null,
      },
    });
  });

  it("parses refdes-prefix read and write results", () => {
    expect(
      refdesPrefixesResultSchema.parse({
        defaults: ["C", "R", "U"],
        custom: ["PS", "XU"],
        path: "C:\\Users\\Reliability\\.refdes_extractor_config.json",
      }).custom,
    ).toEqual(["PS", "XU"]);

    expect(
      writeRefdesPrefixesResultSchema.parse({
        custom: ["XU"],
        path: "C:\\Users\\Reliability\\.refdes_extractor_config.json",
        restart_required: true,
      }).restart_required,
    ).toBe(true);

    // A malformed write result (missing restart_required) must be rejected.
    expect(() =>
      writeRefdesPrefixesResultSchema.parse({ custom: [], path: "x" }),
    ).toThrow();
  });
});
