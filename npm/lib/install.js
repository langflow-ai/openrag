#!/usr/bin/env node

const { execSync, execFileSync } = require("child_process");

const PACKAGE = "openrag";
const VERSION = require("../package.json").version;
const SPEC = `${PACKAGE}==${VERSION}`;

function log(msg) {
  console.log(`\x1b[36m[openrag]\x1b[0m ${msg}`);
}

function findPython() {
  for (const cmd of ["python3", "python"]) {
    try {
      const version = execFileSync(cmd, ["--version"], {
        encoding: "utf-8",
        stdio: ["pipe", "pipe", "pipe"],
      }).trim();

      const match = version.match(/Python (\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 13))) {
        return { cmd, version };
      }
    } catch {}
  }
  return null;
}

function findInstaller() {
  for (const cmd of ["uv", "pipx"]) {
    try {
      execFileSync(cmd, ["--version"], { stdio: "pipe" });
      return cmd;
    } catch {}
  }
  return "pip";
}

function install() {
  console.log("");
  log("OpenRAG is a Python application.");
  log("This npm package is a bootstrap installer — it will install the");
  log(`Python ${PACKAGE} package (v${VERSION}) on your system.`);
  console.log("");

  const python = findPython();
  if (!python) {
    console.error(
      `\x1b[31m[openrag] Python >= 3.13 is required but was not found on your system.\x1b[0m\n` +
        `\n` +
        `  OpenRAG is built with Python and needs Python 3.13+ to run.\n` +
        `  Install Python, then re-run: npm install -g openrag\n` +
        `\n` +
        `  Download Python: https://www.python.org/downloads/\n`
    );
    process.exit(1);
  }

  log(`Found ${python.version} (${python.cmd})`);

  const installer = findInstaller();
  log(`Installing ${SPEC} via ${installer}...`);
  console.log("");

  try {
    switch (installer) {
      case "uv":
        execSync(`uv tool install ${SPEC}`, { stdio: "inherit" });
        break;
      case "pipx":
        execSync(`pipx install ${SPEC}`, { stdio: "inherit" });
        break;
      default:
        execSync(`${python.cmd} -m pip install ${SPEC}`, { stdio: "inherit" });
        break;
    }
    console.log("");
    log(`\x1b[32mInstalled successfully.\x1b[0m`);
    log(`Run \x1b[1mopenrag\x1b[0m to get started.`);
    console.log("");
  } catch (err) {
    console.error("");
    console.error(`\x1b[31m[openrag] Failed to install the Python package.\x1b[0m`);
    console.error(`\x1b[31m[openrag] You can install it manually:\x1b[0m`);
    console.error(`\x1b[31m[openrag]   pip install ${SPEC}\x1b[0m`);
    console.error("");
    process.exit(1);
  }
}

install();
