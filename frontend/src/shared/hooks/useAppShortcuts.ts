import { useEffect } from "react";
import { useShellStore, type ToolId } from "../../stores/shellStore";
import { useThemeStore } from "../../stores/themeStore";
import {
  isEditableKeyboardTarget,
  matchesAltShortcut,
  matchesPrimaryShortcut,
} from "./shortcutUtils";

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
  const toggleContext = useShellStore((state) => state.toggleContext);
  const setThemeMode = useThemeStore((state) => state.setMode);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      // Guard: do not intercept number/bracket/letter keys while the user is
      // typing. Without this, Ctrl+1 while focused in a text field would
      // switch tools instead of inserting "1".
      if (isEditableKeyboardTarget(event.target)) {
        return;
      }
      if (matchesPrimaryShortcut(event, event.key)) {
        const numericIndex = Number.parseInt(event.key, 10);
        if (!Number.isNaN(numericIndex) && numericIndex >= 1 && numericIndex <= orderedTools.length) {
          event.preventDefault();
          setActiveToolId(orderedTools[numericIndex - 1]);
          return;
        }
      }

      if (matchesPrimaryShortcut(event, "]")) {
        event.preventDefault();
        const currentIndex = orderedTools.indexOf(activeToolId);
        setActiveToolId(orderedTools[(currentIndex + 1) % orderedTools.length]);
        return;
      }

      if (matchesPrimaryShortcut(event, "[")) {
        event.preventDefault();
        const currentIndex = orderedTools.indexOf(activeToolId);
        setActiveToolId(orderedTools[(currentIndex - 1 + orderedTools.length) % orderedTools.length]);
        return;
      }

      // Design handoff principle D: ⌘R / Ctrl+R toggles the Review drawer.
      // Uppercase "R" matches regardless of the Shift state since browsers
      // report it differently across platforms; the helper already strips
      // Shift via its caseless compare.
      if (matchesPrimaryShortcut(event, "r")) {
        event.preventDefault();
        toggleContext();
        return;
      }

      // Alt-only, matching the documented ⌥L / ⌥D bindings. The previous
      // wiring demanded Ctrl+Alt, which contradicted DESIGN_SYSTEM.md and
      // collided with AltGr on international layouts.
      if (matchesAltShortcut(event, "l")) {
        event.preventDefault();
        setThemeMode("light_precision");
        return;
      }

      if (matchesAltShortcut(event, "d")) {
        event.preventDefault();
        setThemeMode("dark_precision");
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeToolId, setActiveToolId, setThemeMode, toggleContext]);
}
