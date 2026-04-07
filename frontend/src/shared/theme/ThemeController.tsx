import { useEffect, useMemo, useState } from "react";
import { useThemeStore, type ThemeId } from "../../stores/themeStore";

function getSystemTheme(): ThemeId {
  if (typeof window === "undefined") {
    return "light_precision";
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark_precision"
    : "light_precision";
}

export function useResolvedTheme(): ThemeId {
  const mode = useThemeStore((state) => state.mode);
  const [systemTheme, setSystemTheme] = useState<ThemeId>(() => getSystemTheme());

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => {
      setSystemTheme(mediaQuery.matches ? "dark_precision" : "light_precision");
    };

    listener();
    mediaQuery.addEventListener("change", listener);
    return () => mediaQuery.removeEventListener("change", listener);
  }, []);

  return useMemo(() => (mode === "system" ? systemTheme : mode), [mode, systemTheme]);
}

export function ThemeController() {
  const mode = useThemeStore((state) => state.mode);
  const resolvedTheme = useResolvedTheme();

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.dataset.themeMode = mode;
    const darkThemes: ThemeId[] = [
      "dark_precision",
      "midnight_blue",
      "high_contrast",
      "synthwave",
    ];
    document.documentElement.style.colorScheme = darkThemes.includes(resolvedTheme)
      ? "dark"
      : "light";
  }, [mode, resolvedTheme]);

  return null;
}
