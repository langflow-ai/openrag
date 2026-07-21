#!/usr/bin/env node
const { execSync } = require("child_process");

// Detect architecture
const arch = process.arch;
const isPPC64 = arch === "ppc64";

// Choose build command
const buildCmd = isPPC64 ? "next build --webpack" : "next build";

console.log(`Building for ${arch} using: ${buildCmd}`);

// Execute build
try {
  execSync(buildCmd, { stdio: "inherit" });
} catch (error) {
  process.exit(error.status || 1);
}
