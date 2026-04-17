import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));

// Expose the repo-root ``package.json`` version to the React bundle as
// ``__APP_VERSION__``. Keeps Settings › About honest — previously the
// version number was hand-typed in ``SettingsTool.tsx`` and drifted. The
// single source of truth is now ``scripts/bump-version.mjs`` which the
// release gate verifies via ``npm run version:check``.
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
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      reportsDirectory: "../logs/frontend-coverage",
    },
  },
});
