import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { arch, platform } from "node:os";
import { join } from "node:path";

const mode = process.argv[2] || "dev";
const extraArgs = process.argv.slice(3);
const cargoBin = join(process.env.USERPROFILE || "", ".cargo", "bin");
const env = {
  ...process.env,
  PATH: `${cargoBin};${process.env.PATH || ""}`,
};

const readiness = spawnSync("node", ["./scripts/tauri-readiness.mjs"], {
  shell: true,
  stdio: "inherit",
  env,
});

if (readiness.status !== 0) {
  process.exit(readiness.status ?? 1);
}

if (platform() === "win32") {
  const devCommand = resolveVsDevCommand();
  const rustupToolchain = resolveWindowsRustupToolchain();
  const target = resolveWindowsBuildTarget();
  const args = [mode, ...extraArgs];

  if (target) {
    args.push("--target", target);
  }

  const result = spawnSync("cmd.exe", ["/d", "/s", "/c", `.\\scripts\\tauri-msvc.cmd ${args.join(" ")}`], {
    stdio: "inherit",
    env: {
      ...env,
      ...(rustupToolchain ? { RUSTUP_TOOLCHAIN: rustupToolchain } : {}),
      VS_DEV_CMD: devCommand || "",
      TAURI_CMD: ".\\node_modules\\.bin\\tauri.cmd",
    },
  });

  process.exit(result.status ?? 1);
}

  const result = spawnSync("./node_modules/.bin/tauri", [mode, ...extraArgs], {
    shell: true,
    stdio: "inherit",
    env,
});

process.exit(result.status ?? 1);

function resolveVsDevCommand() {
  const standardVsWhere = "C:\\Program Files (x86)\\Microsoft Visual Studio\\Installer\\vswhere.exe";

  if (!existsSync(standardVsWhere)) {
    return null;
  }

  const found = spawnSync(
    standardVsWhere,
    [
      "-latest",
      "-products",
      "*",
      "-requires",
      "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
      "-property",
      "installationPath",
    ],
    { encoding: "utf8" },
  );

  const installationPath = (found.stdout || "").trim();
  if (!installationPath) {
    return null;
  }

  const candidates = [
    join(installationPath, "Common7", "Tools", "VsDevCmd.bat"),
    join(installationPath, "VC", "Auxiliary", "Build", "vcvars64.bat"),
  ];

  return candidates.find((candidate) => existsSync(candidate)) ?? null;
}

function resolveWindowsBuildTarget() {
  if (!needsWindowsX64Fallback()) {
    return null;
  }

  return "x86_64-pc-windows-msvc";
}

function resolveWindowsRustupToolchain() {
  if (!needsWindowsX64Fallback()) {
    return null;
  }

  return "stable-x86_64-pc-windows-msvc";
}

function needsWindowsX64Fallback() {
  if (arch() !== "arm64") {
    return false;
  }

  const arm64Linkers = [
    "C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Tools\\MSVC\\14.44.35207\\bin\\Hostarm64\\arm64\\link.exe",
    "C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Tools\\MSVC\\14.44.35207\\bin\\Hostx64\\arm64\\link.exe",
  ];

  return !arm64Linkers.some((candidate) => existsSync(candidate));
}
