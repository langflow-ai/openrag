#!/usr/bin/env node

const { execFileSync, execSync } = require("child_process");
const { resolve } = require("path");

function findBinary() {
  // Check common locations for the openrag binary
  const candidates = ["openrag"];

  for (const cmd of candidates) {
    try {
      // Use 'which' on unix, 'where' on windows
      const whichCmd = process.platform === "win32" ? "where" : "which";
      const location = execFileSync(whichCmd, [cmd], {
        encoding: "utf-8",
        stdio: ["pipe", "pipe", "pipe"],
      }).trim().split("\n")[0];

      if (location) return location;
    } catch {}
  }

  // Also check uv tool path
  try {
    const result = execSync("uv tool run --from openrag openrag --help", {
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"],
    });
    return null; // signal to use uv tool run
  } catch {}

  return null;
}

function main() {
  const args = process.argv.slice(2);
  const binary = findBinary();

  try {
    if (binary) {
      const result = execFileSync(binary, args, {
        stdio: "inherit",
        env: process.env,
      });
    } else {
      // Fallback: try uv tool run
      execSync(`uv tool run --from openrag openrag ${args.map(a => `"${a}"`).join(" ")}`, {
        stdio: "inherit",
        env: process.env,
      });
    }
  } catch (err) {
    if (err.status != null) {
      process.exit(err.status);
    }
    console.error(
      `\x1b[31mCould not find openrag. Try reinstalling:\x1b[0m\n` +
        `  npm install -g openrag\n` +
        `  # or\n` +
        `  pip install openrag`
    );
    process.exit(1);
  }
}

main();
