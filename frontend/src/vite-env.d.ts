/// <reference types="vite/client" />

// Injected by Vite at build time from the repo-root ``package.json``.
// See ``frontend/vite.config.ts`` (the ``define`` block). Kept as a
// declaration so ``SettingsTool.tsx`` can read the version without a
// runtime JSON import that would bloat the bundle.
declare const __APP_VERSION__: string;
