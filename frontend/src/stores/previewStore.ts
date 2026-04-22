import { create } from "zustand";
import type { OutputPreview } from "../contracts/sidecar";
import type { ToolId } from "./shellStore";

/**
 * Per-tool cache of the last `output_preview` returned by `validate_run`.
 *
 * The Review drawer (design handoff principle D, phase 4) reads from this
 * store to render a preview of what each tool would produce. Tools write
 * to it from their validate-run handlers; clearing is owned by the tool
 * when inputs change so a stale preview doesn't outlive its source state.
 */
interface PreviewSnapshot {
  preview: OutputPreview | null;
  updatedAt: string;
}

interface PreviewState {
  byTool: Record<string, PreviewSnapshot | undefined>;
  setPreview: (toolId: ToolId, preview: OutputPreview | null | undefined) => void;
  clearPreview: (toolId: ToolId) => void;
  clearAll: () => void;
}

export const usePreviewStore = create<PreviewState>((set) => ({
  byTool: {},
  setPreview: (toolId, preview) =>
    set((state) => ({
      byTool: {
        ...state.byTool,
        [toolId]: {
          preview: preview ?? null,
          updatedAt: new Date().toISOString(),
        },
      },
    })),
  clearPreview: (toolId) =>
    set((state) => {
      const next = { ...state.byTool };
      delete next[toolId];
      return { byTool: next };
    }),
  clearAll: () => set({ byTool: {} }),
}));
