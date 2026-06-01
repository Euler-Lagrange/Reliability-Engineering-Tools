import { describe, expect, it } from "vitest";
import {
  fletConfigResultSchema,
  inspectionResultSchema,
  sidecarRunEventSchema,
} from "./sidecar";

describe("sidecar protocol schemas", () => {
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
        },
      }),
    ).toMatchObject({
      kind: "ack",
      payload: {
        run_id: "run_001",
        session_generation: 3,
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
});
