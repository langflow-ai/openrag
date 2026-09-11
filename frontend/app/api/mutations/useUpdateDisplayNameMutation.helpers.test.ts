import assert from "node:assert/strict";
import { describe, it } from "vitest";
import { patchDisplayName } from "./useUpdateDisplayNameMutation.helpers.ts";

// ---------------------------------------------------------------------------
// Minimal fetch mock factory
// ---------------------------------------------------------------------------

function makeFetch(
  status: number,
  body: unknown,
  jsonThrows = false,
): typeof fetch {
  return async (_url: RequestInfo | URL, _init?: RequestInit) => {
    const jsonFn = jsonThrows
      ? async () => {
          throw new Error("not json");
        }
      : async () => body;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: jsonFn,
    } as unknown as Response;
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("patchDisplayName — success", () => {
  it("returns the parsed body on 200", async () => {
    const result = await patchDisplayName(
      "Alice",
      makeFetch(200, { display_name: "Alice" }),
    );
    assert.deepEqual(result, { display_name: "Alice" });
  });

  it("sends null display_name correctly", async () => {
    let sentBody: string | undefined;
    const mockFetch: typeof fetch = async (_url, init) => {
      sentBody = init?.body as string;
      return {
        ok: true,
        status: 200,
        json: async () => ({ display_name: null }),
      } as unknown as Response;
    };
    const result = await patchDisplayName(null, mockFetch);
    assert.deepEqual(result, { display_name: null });
    assert.deepEqual(JSON.parse(sentBody!), { display_name: null });
  });

  it("sends the correct method, path, and content-type header", async () => {
    let capturedUrl: string | undefined;
    let capturedInit: RequestInit | undefined;
    const mockFetch: typeof fetch = async (url, init) => {
      capturedUrl = url as string;
      capturedInit = init;
      return {
        ok: true,
        status: 200,
        json: async () => ({ display_name: "Bob" }),
      } as unknown as Response;
    };
    await patchDisplayName("Bob", mockFetch);
    assert.equal(capturedUrl, "/api/users/me/display-name");
    assert.equal(capturedInit?.method, "PATCH");
    assert.equal(
      (capturedInit?.headers as Record<string, string>)["Content-Type"],
      "application/json",
    );
  });
});

describe("patchDisplayName — API error with detail", () => {
  it("throws with the API detail message on 4xx", async () => {
    await assert.rejects(
      () => patchDisplayName("X", makeFetch(400, { detail: "Name too long" })),
      (err: Error) => {
        assert.equal(err.message, "Name too long");
        return true;
      },
    );
  });

  it("throws with the API detail message on 500", async () => {
    await assert.rejects(
      () => patchDisplayName("X", makeFetch(500, { detail: "Server error" })),
      (err: Error) => {
        assert.equal(err.message, "Server error");
        return true;
      },
    );
  });
});

describe("patchDisplayName — non-JSON failure body", () => {
  it("falls back to default message when error body is not JSON", async () => {
    await assert.rejects(
      () => patchDisplayName("X", makeFetch(503, null, /* jsonThrows */ true)),
      (err: Error) => {
        assert.equal(err.message, "Failed to save display name");
        return true;
      },
    );
  });

  it("falls back to default message when error body has no detail field", async () => {
    await assert.rejects(
      () => patchDisplayName("X", makeFetch(422, { other: "field" })),
      (err: Error) => {
        assert.equal(err.message, "Failed to save display name");
        return true;
      },
    );
  });
});
