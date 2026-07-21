import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const cargoBin = join(process.env.USERPROFILE || "", ".cargo", "bin");
const env = {
  ...process.env,
  PATH: `${cargoBin};${process.env.PATH || ""}`,
};

function checkCommand(command, args = ["--version"]) {
  const result = spawnSync(command, args, { encoding: "utf8", env });
  return {
    ok: result.status === 0,
    output: (result.stdout || result.stderr || "").trim(),
  };
}

const checks = [
  {
    label: "cargo",
    result: checkCommand("cargo"),
    help: "Install the Rust toolchain so Tauri can compile the desktop shell.",
  },
  {
    label: "rustc",
    result: checkCommand("rustc"),
    help: "Install the Rust compiler; Tauri packaging cannot proceed without it.",
  },
];

const tauriConfigPath = join(root, "src-tauri", "tauri.conf.json");
const hasConfig = existsSync(tauriConfigPath);

console.log("Reliability Tools Desktop Readiness");
console.log("=========================");
console.log("");

for (const check of checks) {
  console.log(`${check.result.ok ? "OK " : "MISS"} ${check.label}`);
  if (check.result.output) {
    console.log(`     ${check.result.output}`);
  }
  if (!check.result.ok) {
    console.log(`     ${check.help}`);
  }
}

console.log(`${hasConfig ? "OK " : "MISS"} src-tauri/tauri.conf.json`);
if (!hasConfig) {
  console.log("     Add the Tauri config scaffold before attempting desktop packaging.");
}

console.log("");
console.log("Manual prerequisites not auto-verified:");
console.log("- MSVC build tools / Visual Studio C++ workload");
console.log("- WebView2-compatible Windows runtime");
console.log("- Chosen Tauri CLI installation method");

const ready = checks.every((check) => check.result.ok) && hasConfig;
process.exitCode = ready ? 0 : 1;
