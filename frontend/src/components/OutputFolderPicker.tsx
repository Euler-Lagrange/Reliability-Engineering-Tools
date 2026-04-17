import { FolderOpen } from "@phosphor-icons/react";

import { backendClient } from "../shared/backend/client";
import { useNotificationStore } from "../stores/notificationStore";

import { OptionsField } from "./primitives/OptionsField";

interface OutputFolderPickerProps {
  label?: string;
  hint?: string;
  value: string | null;
  onChange: (path: string | null) => void;
  emptyLabel?: string;
}

/**
 * Reusable output-folder picker. Mirrors the FMEA tool's output-folder UI
 * so every tool exposes the same affordance and wiring to
 * ``backendClient.openDirectory``. Consumers own the persisted value in
 * their Zustand slice and pass ``onChange`` to update it.
 */
export function OutputFolderPicker({
  label = "Output Folder",
  hint = "Defaults to the folder of your first loaded input.",
  value,
  onChange,
  emptyLabel = "Default: alongside first input",
}: OutputFolderPickerProps) {
  const pushNotification = useNotificationStore((state) => state.push);

  const handleBrowse = async () => {
    if (backendClient.runtimeMode !== "desktop-bridge") {
      pushNotification({
        tone: "info",
        title: "Desktop runtime required",
        detail:
          "Picking an output folder uses the native OS dialog — run the Tauri desktop shell to set a real path.",
      });
      return;
    }

    try {
      const picked = await backendClient.openDirectory(value ?? undefined);
      if (picked) {
        onChange(picked);
      }
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : "Unknown folder picker failure";
      pushNotification({
        tone: "error",
        title: "Folder picker failed",
        detail,
      });
    }
  };

  return (
    <OptionsField label={label} hint={hint}>
      <div className="fmea-output-folder">
        <code className="fmea-output-folder__path" title={value ?? undefined}>
          {value ?? emptyLabel}
        </code>
        <div className="fmea-output-folder__actions">
          <button
            type="button"
            className="ghost-button fmea-output-folder__button"
            onClick={() => {
              void handleBrowse();
            }}
          >
            <FolderOpen size={14} weight="regular" aria-hidden="true" />
            <span>Change…</span>
          </button>
          {value ? (
            <button
              type="button"
              className="ghost-button"
              onClick={() => onChange(null)}
            >
              Reset
            </button>
          ) : null}
        </div>
      </div>
    </OptionsField>
  );
}
