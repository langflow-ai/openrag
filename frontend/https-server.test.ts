import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { copyFile, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import tls from "node:tls";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

const wrapper = resolve(process.cwd(), "https-server.js");
const fixtures: string[] = [];
const children: ChildProcess[] = [];

let certDir: string;
let certFile: string;
let keyFile: string;
let certPem: string;

// Stand-in for the generated standalone server.js: plain http, ephemeral port.
const FIXTURE_SERVER = `
const http = require("node:http");
const server = http.createServer((req, res) => res.end("ok"));
server.listen(0, "127.0.0.1", () =>
  console.log("PORT=" + server.address().port),
);
`;

async function createFixture() {
  const directory = await mkdtemp(join(tmpdir(), "openrag-https-server-"));
  fixtures.push(directory);
  await copyFile(wrapper, join(directory, "https-server.js"));
  await writeFile(join(directory, "server.js"), FIXTURE_SERVER);
  return directory;
}

function launch(directory: string, env: Record<string, string>) {
  const child = spawn("node", ["https-server.js"], {
    cwd: directory,
    env: { PATH: process.env.PATH ?? "", ...env },
  });
  children.push(child);
  return child;
}

function waitForPort(child: ChildProcess): Promise<number> {
  return new Promise((resolvePort, reject) => {
    let output = "";
    child.stdout?.on("data", (chunk) => {
      output += chunk;
      const match = output.match(/PORT=(\d+)/);
      if (match) resolvePort(Number(match[1]));
    });
    child.on("exit", (code) => reject(new Error(`exited early: ${code}`)));
  });
}

// Raw sockets rather than fetch/http(s).get: the shared Vitest setup installs
// MSW, which rejects any real HTTP request issued from the test process.
function get(port: number, secure: boolean): Promise<string> {
  return new Promise((resolveBody, reject) => {
    const request =
      "GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n";
    const socket = secure
      ? tls.connect({
          host: "127.0.0.1",
          port,
          ca: certPem,
          servername: "localhost",
        })
      : net.connect({ host: "127.0.0.1", port });
    let body = "";
    socket.setEncoding("utf8");
    socket.on(secure ? "secureConnect" : "connect", () =>
      socket.write(request),
    );
    socket.on("data", (chunk) => {
      body += chunk;
    });
    socket.on("end", () => resolveBody(body));
    socket.on("error", reject);
  });
}

beforeAll(async () => {
  certDir = await mkdtemp(join(tmpdir(), "openrag-https-cert-"));
  certFile = join(certDir, "tls.crt");
  keyFile = join(certDir, "tls.key");
  const result = spawnSync(
    "openssl",
    [
      "req",
      "-x509",
      "-newkey",
      "rsa:2048",
      "-nodes",
      "-days",
      "1",
      "-subj",
      "/CN=localhost",
      "-addext",
      "subjectAltName=IP:127.0.0.1,DNS:localhost",
      "-keyout",
      keyFile,
      "-out",
      certFile,
    ],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(`openssl failed: ${result.stderr}`);
  }
  certPem = await readFile(certFile, "utf8");
});

afterAll(async () => {
  await rm(certDir, { recursive: true, force: true });
});

afterEach(async () => {
  for (const child of children.splice(0)) child.kill();
  await Promise.all(
    fixtures
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

describe("https-server.js", () => {
  it("serves HTTPS when both TLS_CERT_PATH and TLS_KEY_PATH are set", async () => {
    const directory = await createFixture();
    const child = launch(directory, {
      TLS_CERT_PATH: certFile,
      TLS_KEY_PATH: keyFile,
    });
    const port = await waitForPort(child);

    await expect(get(port, true)).resolves.toMatch(/200 OK[\s\S]*ok$/);
    await expect(get(port, false)).resolves.not.toMatch(/200 OK/);
  });

  it("serves plain HTTP when no TLS variables are set", async () => {
    const directory = await createFixture();
    const child = launch(directory, {});
    const port = await waitForPort(child);

    await expect(get(port, false)).resolves.toMatch(/200 OK[\s\S]*ok$/);
  });

  it("refuses to start when only one of the TLS variables is set", async () => {
    const directory = await createFixture();
    const child = launch(directory, { TLS_CERT_PATH: join(directory, "x") });
    const stderr: string[] = [];
    child.stderr?.on("data", (chunk) => stderr.push(String(chunk)));

    const code = await new Promise((done) => child.on("exit", done));

    expect(code).toBe(1);
    expect(stderr.join("")).toContain("must be set together");
  });
});
