import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));

// Expose the repo-root ``package.json`` version to the React bundle as
// ``__APP_VERSION__``. Keeps Settings › About honest — previously the
// version number was hand-typed in ``SettingsTool.tsx`` and drifted. The
// single source of truth is ``package.json``; ``scripts/bump-version.mjs``
// syncs it with Cargo.toml / tauri.conf.json. ``npm run version:check``
// verifies lockstep independently and is release.bat step 2.
const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL("../package.json", import.meta.url)), "utf8"),
);

export default defineConfig({
  root: frontendRoot,
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./vitest.setup.ts",
    // Companion to the raised `asyncUtilTimeout` in vitest.setup.ts. A test
    // that renders the App shell and switches tools chains several lazy-chunk
    // -gated waits; under heavy load their sum can exceed the 5000ms default
    // testTimeout even when no single wait does. Raising the per-test ceiling
    // to 15000ms (matching the existing FmeaTool.test.tsx local override) gives
    // those multi-wait tests room AND keeps the 5000ms asyncUtilTimeout below
    // it, so RTL's helpful "Unable to find ..." message still wins on a real
    // failure. hookTimeout and the fork pool are deliberately left at their
    // defaults: the root cause is the too-tight per-wait budget, not worker
    // contention — reducing pool size would only mask timing and slow the
    // suite, and does nothing against EXTERNAL load (builds, AV).
    testTimeout: 15000,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      reportsDirectory: "../logs/frontend-coverage",
    },
  },
});
