#!/usr/bin/env node
/**
 * Build the npm package and regenerate the bridge asset shipped by the Python
 * package. Keeping both outputs in one script is what prevents the bundled
 * bridge from drifting away from `src/index.ts`.
 */
import { build } from "esbuild";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const dist = path.join(root, "dist");
const entry = path.join(root, "src", "index.ts");

const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
const banner = { js: `/*! cakeui bridge ${pkg.version} */` };
const shared = {
  entryPoints: [entry],
  bundle: true,
  target: "es2020",
  banner,
  legalComments: "inline",
  logLevel: "info",
};

mkdirSync(dist, { recursive: true });

// 1. ESM build for bundlers (Vite, webpack, esbuild users).
await build({ ...shared, format: "esm", outfile: path.join(dist, "index.mjs") });

// 2. Classic <script> build: exposes `window.cakeui`.
await build({
  ...shared,
  format: "iife",
  globalName: "cakeui",
  outfile: path.join(dist, "cakeui.global.js"),
});

// 3. Type declarations.
execFileSync(path.join(root, "node_modules", ".bin", "tsc"), ["-p", "."], {
  cwd: root,
  stdio: "inherit",
});

// 4. Assets served by the Python runtime to file:// and bundler frontends:
//    the IIFE build (window.cakeui) and the ESM build (import { invoke }).
const bridgeDir = path.resolve(root, "..", "python", "src", "cakeui");
copyFileSync(path.join(dist, "cakeui.global.js"), path.join(bridgeDir, "_bridge.js"));
copyFileSync(path.join(dist, "index.mjs"), path.join(bridgeDir, "_bridge.mjs"));
copyFileSync(path.join(dist, "index.d.ts"), path.join(bridgeDir, "_bridge.d.ts"));
console.log(`bridge assets written to ${path.relative(root, bridgeDir)}`);
