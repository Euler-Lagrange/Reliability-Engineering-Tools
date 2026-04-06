import { useEffect } from "react";
import { useShellStore, type ToolId } from "../../stores/shellStore";
import { useThemeStore } from "../../stores/themeStore";

const orderedTools: ToolId[] = [
  "dark_star_fmea",
  "bom_compare",
  "failure_rate",
  "refdes_extractor",
  "settings",
];

export function useAppShortcuts() {
  const activeToolId = useShellStore((state) => state.activeToolId);
  const setActiveToolId = useShellStore((state) => state.setActiveToolId);
  const setThemeMode = useThemeStore((state) => state.setMode);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.ctrlKey && !event.shiftKey) {
        const numericIndex = Number.parseInt(event.key, 10);
        if (!Number.isNaN(numericIndex) && numericIndex >= 1 && numericIndex <= orderedTools.length) {
          event.preventDefault();
          setActiveToolId(orderedTools[numericIndex - 1]);
          return;
        }
      }

      if (event.ctrlKey && event.key === "]") {
        event.preventDefault();
        const currentIndex = orderedTools.indexOf(activeToolId);
        setActiveToolId(orderedTools[(currentIndex + 1) % orderedTools.length]);
        return;
      }

      if (event.ctrlKey && event.key === "[") {
        event.preventDefault();
        const currentIndex = orderedTools.indexOf(activeToolId);
        setActiveToolId(orderedTools[(currentIndex - 1 + orderedTools.length) % orderedTools.length]);
        return;
      }

      if (event.ctrlKey && event.altKey && event.key.toLowerCase() === "l") {
        event.preventDefault();
        setThemeMode("light_precision");
        return;
      }

      if (event.ctrlKey && event.altKey && event.key.toLowerCase() === "d") {
        event.preventDefault();
        setThemeMode("dark_precision");
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeToolId, setActiveToolId, setThemeMode]);
}
