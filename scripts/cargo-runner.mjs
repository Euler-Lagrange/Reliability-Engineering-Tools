import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { arch, platform } from "node:os";
import { join } from "node:path";

// Thin wrapper around `cargo` that prepares the MSVC environment on
// Windows, mirroring `scripts/tauri-runner.mjs`. Pass every argument
// through to cargo verbatim, e.g.:
//
//   node ./scripts/cargo-runner.mjs check --manifest-path src-tauri/Cargo.toml --quiet
//
// Without the vcvars setup step, `cargo check` fails with
// `linker link.exe not found` on fresh shells because rustc needs the
// MSVC linker to build proc-macro / build-script binaries.

const cargoBin = join(process.env.USERPROFILE || "", ".cargo", "bin");
const env = {
  ...process.env,
  PATH: `${cargoBin};${process.env.PATH || ""}`,
};

if (platform() !== "win32") {
  const result = spawnSync("cargo", process.argv.slice(2), {
    stdio: "inherit",
    env,
    shell: true,
  });
  process.exit(result.status ?? 1);
}

const devCommand = resolveVsDevCommand();
const rustupToolchain = resolveWindowsRustupToolchain();
const target = resolveWindowsBuildTarget();
const args = [...process.argv.slice(2)];

if (target && !args.includes("--target")) {
  args.push("--target", target);
}

const result = spawnSync("cmd.exe", ["/d", "/s", "/c", `.\\scripts\\cargo-msvc.cmd ${args.join(" ")}`], {
  stdio: "inherit",
  env: {
    ...env,
    ...(rustupToolchain ? { RUSTUP_TOOLCHAIN: rustupToolchain } : {}),
    VS_DEV_CMD: devCommand || "",
  },
});

process.exit(result.status ?? 1);

function resolveVsDevCommand() {
  // Preferred: ask vswhere for the currently-installed VS with VC tools.
  const standardVsWhere = "C:\\Program Files (x86)\\Microsoft Visual Studio\\Installer\\vswhere.exe";

  if (existsSync(standardVsWhere)) {
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
      { encoding: "utf8", shell: false },
    );

    const installationPath = (found.stdout || "").trim();
    if (installationPath) {
      const candidates = [
        join(installationPath, "Common7", "Tools", "VsDevCmd.bat"),
        join(installationPath, "VC", "Auxiliary", "Build", "vcvars64.bat"),
      ];
      const hit = candidates.find((candidate) => existsSync(candidate));
      if (hit) return hit;
    }
  }

  // Fallback: probe the standard install locations directly. Handy when
  // vswhere is missing, broken, or spawn-fails (observed on some shells).
  const fallbackCandidates = [
    "C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat",
    "C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\Common7\\Tools\\VsDevCmd.bat",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\Common7\\Tools\\VsDevCmd.bat",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\Professional\\VC\\Auxiliary\\Build\\vcvars64.bat",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\Enterprise\\VC\\Auxiliary\\Build\\vcvars64.bat",
  ];
  return fallbackCandidates.find((candidate) => existsSync(candidate)) ?? null;
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
