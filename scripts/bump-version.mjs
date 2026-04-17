#!/usr/bin/env node
// Single-source version bumper for the Reliability Tools desktop app.
//
// The version number lives in THREE files today and must stay in lockstep:
//   1. package.json                  -> "version"
//   2. src-tauri/Cargo.toml          -> version = "..."
//   3. src-tauri/tauri.conf.json     -> "version"
//
// ``package-lock.json`` and ``src-tauri/Cargo.lock`` are auto-rewritten by
// the next ``npm install`` / ``cargo build`` and are intentionally NOT
// edited here — doing so manually invites subtle checksum/hash drift.
//
// Usage:
//   node scripts/bump-version.mjs 0.4.2
//   node scripts/bump-version.mjs patch   # 0.4.1 -> 0.4.2
//   node scripts/bump-version.mjs minor   # 0.4.1 -> 0.5.0
//   node scripts/bump-version.mjs major   # 0.4.1 -> 1.0.0
//   node scripts/bump-version.mjs --check # verify all three files agree
//
// After running, the user typically wants to:
//   - run ``npm install`` and a cargo build so lockfiles update,
//   - update ``docs/CHANGELOG.md`` with the new entry,
//   - commit + tag.

import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

const TARGETS = [
  {
    path: resolve(ROOT, "package.json"),
    // JSON top-level "version": "x.y.z" (first match is the root package).
    pattern: /("version"\s*:\s*")([^"]+)(")/,
  },
  {
    path: resolve(ROOT, "src-tauri/Cargo.toml"),
    // TOML: version = "x.y.z" (first match under [package]).
    pattern: /(^version\s*=\s*")([^"]+)(")/m,
  },
  {
    path: resolve(ROOT, "src-tauri/tauri.conf.json"),
    pattern: /("version"\s*:\s*")([^"]+)(")/,
  },
];

const SEMVER = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;

function readCurrent(target) {
  const src = readFileSync(target.path, "utf8");
  const match = src.match(target.pattern);
  if (!match) {
    throw new Error(`Could not locate version field in ${target.path}`);
  }
  return { src, match, current: match[2] };
}

function bumpComponent(current, kind) {
  const match = current.match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!match) {
    throw new Error(`Current version ${current} is not semver — cannot ${kind} bump`);
  }
  let [major, minor, patch] = match.slice(1).map(Number);
  if (kind === "patch") patch += 1;
  else if (kind === "minor") { minor += 1; patch = 0; }
  else if (kind === "major") { major += 1; minor = 0; patch = 0; }
  else throw new Error(`Unknown bump kind: ${kind}`);
  return `${major}.${minor}.${patch}`;
}

function resolveNextVersion(arg, currentVersions) {
  if (["patch", "minor", "major"].includes(arg)) {
    const unique = new Set(currentVersions);
    if (unique.size !== 1) {
      throw new Error(
        `Cannot do a ${arg} bump: sources disagree on current version (${[...unique].join(", ")}). ` +
          `Run --check and fix the drift first.`,
      );
    }
    return bumpComponent(currentVersions[0], arg);
  }
  if (!SEMVER.test(arg)) {
    throw new Error(`"${arg}" is not a semver-compatible version (expected x.y.z).`);
  }
  return arg;
}

function main(argv) {
  const arg = argv[0];
  if (!arg) {
    console.error("usage: node scripts/bump-version.mjs <x.y.z | patch | minor | major | --check>");
    process.exit(2);
  }

  const readings = TARGETS.map((t) => ({ target: t, reading: readCurrent(t) }));
  const currents = readings.map((r) => r.reading.current);

  if (arg === "--check") {
    const unique = new Set(currents);
    for (const { target, reading } of readings) {
      console.log(`  ${reading.current.padEnd(12)}  ${target.path}`);
    }
    if (unique.size === 1) {
      console.log(`version check OK (${currents[0]})`);
      process.exit(0);
    }
    console.error(`version drift detected across ${unique.size} distinct values`);
    process.exit(1);
  }

  const next = resolveNextVersion(arg, currents);

  console.log(`Bumping version -> ${next}`);
  for (const { target, reading } of readings) {
    if (reading.current === next) {
      console.log(`  unchanged   ${target.path}`);
      continue;
    }
    const replaced = reading.src.replace(target.pattern, `$1${next}$3`);
    writeFileSync(target.path, replaced, "utf8");
    console.log(`  ${reading.current} -> ${next}  ${target.path}`);
  }

  console.log("\nNext steps:");
  console.log("  1. Run `npm install` and a cargo build (or `npm run release`) so lockfiles refresh.");
  console.log("  2. Update docs/CHANGELOG.md with the new entry.");
  console.log("  3. Commit and tag (e.g. `git tag v" + next + "`).");
}

try {
  main(process.argv.slice(2));
} catch (err) {
  console.error(`bump-version: ${err.message}`);
  process.exit(1);
}
