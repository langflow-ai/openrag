import assert from "node:assert/strict";
import * as fs from "node:fs";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  afterEach,
  beforeEach,
  describe,
  it,
  onTestFinished,
  vi,
} from "vitest";

// Hoist mocks so they run before any imports.
// node:fs — mock at file level so backend-fetch.ts's `import { readFileSync }`
// resolves to our spy; we swap the implementation per-test.
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual };
});

// undici — backend-fetch.ts loads it via require() inside initialise().
// We mock the whole module here; individual tests override Agent/fetch as needed.
vi.mock("undici", () => ({
  Agent: vi.fn().mockImplementation(() => ({ _isMockAgent: true })),
  fetch: vi.fn().mockResolvedValue(new Response("undici-default")),
}));

describe("getBackendBaseUrl", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it("returns OPENRAG_BACKEND_URL verbatim when set", async () => {
    vi.stubEnv("OPENRAG_BACKEND_URL", "https://my-backend.example.com");
    const { getBackendBaseUrl } = await import("./backend-fetch");
    assert.equal(getBackendBaseUrl(), "https://my-backend.example.com");
  });

  it("strips a trailing slash from OPENRAG_BACKEND_URL", async () => {
    vi.stubEnv("OPENRAG_BACKEND_URL", "https://my-backend.example.com/");
    const { getBackendBaseUrl } = await import("./backend-fetch");
    assert.equal(getBackendBaseUrl(), "https://my-backend.example.com");
  });

  it("falls back to http://localhost:8000 when no env vars are set", async () => {
    vi.stubEnv("OPENRAG_BACKEND_URL", "");
    vi.stubEnv("OPENRAG_BACKEND_HOST", "");
    vi.stubEnv("OPENRAG_BACKEND_PORT", "");
    vi.stubEnv("OPENRAG_BACKEND_SSL", "");
    const { getBackendBaseUrl } = await import("./backend-fetch");
    assert.equal(getBackendBaseUrl(), "http://localhost:8000");
  });

  it("uses OPENRAG_BACKEND_HOST and OPENRAG_BACKEND_PORT", async () => {
    vi.stubEnv("OPENRAG_BACKEND_URL", "");
    vi.stubEnv("OPENRAG_BACKEND_HOST", "backend-svc");
    vi.stubEnv("OPENRAG_BACKEND_PORT", "9000");
    vi.stubEnv("OPENRAG_BACKEND_SSL", "");
    const { getBackendBaseUrl } = await import("./backend-fetch");
    assert.equal(getBackendBaseUrl(), "http://backend-svc:9000");
  });

  it("uses https when OPENRAG_BACKEND_SSL=true", async () => {
    vi.stubEnv("OPENRAG_BACKEND_URL", "");
    vi.stubEnv("OPENRAG_BACKEND_HOST", "backend-svc");
    vi.stubEnv("OPENRAG_BACKEND_PORT", "443");
    vi.stubEnv("OPENRAG_BACKEND_SSL", "true");
    const { getBackendBaseUrl } = await import("./backend-fetch");
    assert.equal(getBackendBaseUrl(), "https://backend-svc:443");
  });
});

describe("backendFetchInit", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it("returns an empty object", async () => {
    const { backendFetchInit } = await import("./backend-fetch");
    assert.deepEqual(backendFetchInit(), {});
  });
});

describe("backendFetch — no custom CA", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("delegates to globalThis.fetch when OPENRAG_BACKEND_CA_CERT_PATH is unset", async () => {
    vi.stubEnv("OPENRAG_BACKEND_CA_CERT_PATH", "");
    const mockResponse = new Response("ok");
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockResponse);

    const { backendFetch } = await import("./backend-fetch");
    const result = await backendFetch("http://localhost:8000/api/health");

    assert.equal(fetchSpy.mock.calls.length, 1);
    assert.equal(
      String(fetchSpy.mock.calls[0][0]),
      "http://localhost:8000/api/health",
    );
    assert.equal(result, mockResponse);
  });
});

describe("backendFetch — with custom CA", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("routes requests through undici.fetch when a CA path is set", async () => {
    // A real file is needed: spying on the `fs` namespace does not intercept
    // backend-fetch's named `readFileSync` import. The Agent only parses the CA
    // on a TLS connect, so a plain-HTTP loopback server avoids any handshake.
    const dir = mkdtempSync(path.join(tmpdir(), "backend-fetch-"));
    const caPath = path.join(dir, "ca.crt");
    writeFileSync(caPath, "FAKE-CA-CERT");
    onTestFinished(() => rmSync(dir, { recursive: true, force: true }));
    vi.stubEnv("OPENRAG_BACKEND_CA_CERT_PATH", caPath);
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => {});

    // undici.fetch opens its own sockets, so MSW never sees this request.
    const backend = createServer((_req, res) => {
      res.setHeader("content-type", "application/json");
      res.end('{"ok":true}');
    });
    await new Promise<void>((resolve) =>
      backend.listen(0, "127.0.0.1", resolve),
    );
    onTestFinished(
      () => new Promise<void>((resolve) => backend.close(() => resolve())),
    );
    const { port } = backend.address() as AddressInfo;

    const { backendFetch } = await import("./backend-fetch");
    const res = await backendFetch(`http://127.0.0.1:${port}/api/health`, {
      method: "GET",
    });

    assert.ok(res.ok, "response should be ok");
    assert.deepEqual(await res.json(), { ok: true });
    assert.ok(
      infoSpy.mock.calls.some((args) =>
        String(args[0]).includes("Custom CA loaded"),
      ),
      "should log that the custom CA was loaded",
    );
  });

  it("falls back to globalThis.fetch when readFileSync throws", async () => {
    vi.stubEnv("OPENRAG_BACKEND_CA_CERT_PATH", "/certs/missing.crt");

    vi.spyOn(fs, "readFileSync").mockImplementation(() => {
      throw new Error("ENOENT: no such file");
    });

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const mockResponse = new Response("fallback");
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockResponse);

    const { backendFetch } = await import("./backend-fetch");
    const result = await backendFetch("https://backend-svc/api/health");

    assert.ok(
      errorSpy.mock.calls.some((args) =>
        String(args[0]).includes("OPENRAG_BACKEND_CA_CERT_PATH"),
      ),
      "should log the CA error",
    );
    assert.equal(fetchSpy.mock.calls.length, 1);
    assert.equal(result, mockResponse);
  });
});
