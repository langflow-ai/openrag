/**
 * Unit tests for OpenRAGClient authentication headers. No server required.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { OpenRAGClient } from "../src";

function capturingFetch(sent: Headers[]): typeof fetch {
  return async (_input, init) => {
    sent.push(new Headers(init?.headers));
    return new Response(JSON.stringify({ agent: {}, knowledge: {} }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
}

describe("OpenRAGClient auth headers", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each(["X-Api-Key", "x-api-key", "X-API-KEY"])(
    "sends the extraHeaders key (%s) once, ignoring OPENRAG_API_KEY",
    async (headerName) => {
      vi.stubEnv("OPENRAG_API_KEY", "env-key");
      const sent: Headers[] = [];
      const client = new OpenRAGClient({
        baseUrl: "http://openrag.test",
        extraHeaders: { "X-Username": "alice", [headerName]: "header-key" },
        fetch: capturingFetch(sent),
      });

      await client.settings.get();

      expect(sent[0].get("x-api-key")).toBe("header-key");
      expect(sent[0].get("x-username")).toBe("alice");
    }
  );

  it("sends apiKey when extraHeaders carry no key", async () => {
    vi.stubEnv("OPENRAG_API_KEY", "");
    const sent: Headers[] = [];
    const client = new OpenRAGClient({
      apiKey: "orag_key",
      baseUrl: "http://openrag.test",
      extraHeaders: { "X-Username": "alice" },
      fetch: capturingFetch(sent),
    });

    await client.settings.get();

    expect(sent[0].get("x-api-key")).toBe("orag_key");
  });
});
