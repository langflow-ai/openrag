/**
 * Unit tests for the feedback SDK surface. Uses a stubbed `fetch`, so no
 * OpenRAG instance is required (unlike integration.test.ts).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AuthenticationError,
  NotFoundError,
  OpenRAGClient,
  ValidationError,
} from "../src";

const SAVED = {
  message_id: "m1",
  rating: "up",
  comment: null,
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
};

function stubFetch(handler: (url: string, init: RequestInit) => Response) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return handler(url, init);
    })
  );
  return calls;
}

const client = () => new OpenRAGClient({ apiKey: "orag_test", baseUrl: "http://test" });
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("chat.feedback", () => {
  it("posts the full value to the message route with the API key", async () => {
    const calls = stubFetch(() => json(SAVED));
    const out = await client().chat.feedback("chat/1", "m1", "up");
    expect(calls[0].url).toBe("http://test/api/v1/chat/chat%2F1/messages/m1/feedback");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ rating: "up", comment: null });
    expect((calls[0].init.headers as Record<string, string>)["X-API-Key"]).toBe("orag_test");
    expect(out).toEqual({
      messageId: "m1",
      rating: "up",
      comment: null,
      createdAt: SAVED.created_at,
      updatedAt: SAVED.updated_at,
    });
  });

  it("sends a comment", async () => {
    const calls = stubFetch(() => json({ ...SAVED, rating: "down", comment: "bad" }));
    const out = await client().chat.feedback("c", "m1", "down", "bad");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ rating: "down", comment: "bad" });
    expect(out.comment).toBe("bad");
  });

  it.each([
    [403, AuthenticationError],
    [404, NotFoundError],
    [422, ValidationError],
  ])("maps HTTP %i to a typed error", async (status, Err) => {
    stubFetch(() => json({ detail: { error: "x" } }, status));
    await expect(client().chat.feedback("c", "m1", "up")).rejects.toBeInstanceOf(Err);
  });
});

describe("message ids", () => {
  it("exposes messageId on create and on history, with the caller's feedback", async () => {
    stubFetch((_url, init) =>
      init.method === "POST"
        ? json({ response: "a", chat_id: "c", sources: [], message_id: "m9" })
        : json({
            chat_id: "c",
            messages: [
              { role: "user", content: "q" },
              { role: "assistant", content: "a", message_id: "m9", feedback: { rating: "up", comment: null, created_at: SAVED.created_at, updated_at: SAVED.updated_at } },
            ],
          })
    );
    const c = client();
    expect((await c.chat.create({ message: "q" })).messageId).toBe("m9");
    const detail = await c.chat.get("c");
    expect(detail.messages[0].messageId).toBeNull();
    expect(detail.messages[1].messageId).toBe("m9");
    expect(detail.messages[1].feedback?.rating).toBe("up");
  });

  it("surfaces messageId on the stream's done event", async () => {
    const sse =
      'data: {"type":"content","delta":"hi"}\n\n' +
      'data: {"type":"done","chat_id":"c","message_id":"m5"}\n\n';
    stubFetch(() => new Response(sse, { headers: { "content-type": "text/event-stream" } }));
    const stream = await client().chat.stream({ message: "q" });
    const events = [];
    for await (const e of stream) events.push(e);
    expect(stream.messageId).toBe("m5");
    expect(events.at(-1)).toMatchObject({ type: "done", messageId: "m5" });
  });
});
