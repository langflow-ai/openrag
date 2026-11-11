import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  cookieString: "session=abc",
  incoming: new Map<string, string>(),
  backendFetch: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({ toString: () => mocks.cookieString }),
  headers: async () => ({
    get: (name: string) => mocks.incoming.get(name) ?? null,
  }),
}));

vi.mock("@/lib/backend-fetch", () => ({
  getBackendBaseUrl: () => "https://backend.test",
  backendFetch: mocks.backendFetch,
}));

import { fetchFromBackend } from "./fetch-server";

function lastCall() {
  const [url, init] = mocks.backendFetch.mock.calls.at(-1) as [
    string,
    RequestInit & { headers: Record<string, string> },
  ];
  return { url, init };
}

describe("fetchFromBackend", () => {
  beforeEach(() => {
    mocks.incoming.clear();
    mocks.cookieString = "session=abc";
    mocks.backendFetch.mockReset();
    mocks.backendFetch.mockResolvedValue(new Response("ok"));
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("targets the backend base URL and forwards the cookie with no-store", async () => {
    await fetchFromBackend("api/health");

    const { url, init } = lastCall();
    assert.equal(url, "https://backend.test/api/health");
    assert.equal(init.cache, "no-store");
    assert.deepEqual(init.headers, { Cookie: "session=abc" });
  });

  it("forwards the default auth and IBM credential headers when present", async () => {
    mocks.incoming.set("authorization", "Bearer jwt");
    mocks.incoming.set("x-ibm-lh-credentials", "creds");

    await fetchFromBackend("api/settings");

    assert.deepEqual(lastCall().init.headers, {
      Cookie: "session=abc",
      authorization: "Bearer jwt",
      "x-ibm-lh-credentials": "creds",
    });
  });

  it("honors the env-overridden header names (lower-cased)", async () => {
    vi.stubEnv("OPENRAG_JWT_AUTH_HEADER", "X-Custom-JWT");
    vi.stubEnv("IBM_CREDENTIALS_HEADER", "X-Custom-Creds");
    mocks.incoming.set("x-custom-jwt", "tok");
    mocks.incoming.set("x-custom-creds", "c");
    mocks.incoming.set("authorization", "ignored");

    await fetchFromBackend("api/settings");

    assert.deepEqual(lastCall().init.headers, {
      Cookie: "session=abc",
      "x-custom-jwt": "tok",
      "x-custom-creds": "c",
    });
  });

  it("lets caller-supplied headers and init override the forwarded ones", async () => {
    await fetchFromBackend("api/x", {
      method: "POST",
      headers: { Cookie: "override=1" },
    });

    const { init } = lastCall();
    assert.equal(init.method, "POST");
    assert.deepEqual(init.headers, { Cookie: "override=1" });
  });
});
