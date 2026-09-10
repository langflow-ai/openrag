import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import { act, renderHook, waitFor } from "@/test-utils/render";
import { useChatStreaming } from "./useChatStreaming";

/**
 * The most-fixed file in the frontend: 6 of 16 commits in the last year were
 * bug fixes (#2127 "surface provider errors in chat instead of generic
 * connection failures", #1534 "make watsonx work in chat", #859 "use correct
 * error handling for chat messages and ingestion", "Error handling for chats
 * that are slow to respond").
 *
 * The transport is newline-delimited JSON, not SSE — the hook splits on "\n"
 * and JSON.parses each complete line, buffering any partial trailing line.
 *
 * Real under test: the whole of lib/chat-stream-parsers and
 * lib/chat-stream-errors. Only the chat context is mocked, because useChat()
 * throws outside its provider.
 */

const refreshConversations = vi.fn();
vi.mock("@/contexts/chat-context", () => ({
  useChat: () => ({ refreshConversations }),
}));

const ENDPOINT = "/api/langflow";

/** A text delta in the OpenAI-style shape the hook's first parser accepts. */
function textChunk(text: string) {
  return { object: "response.chunk", delta: { content: text } };
}

/**
 * Serves `endpoint` as an NDJSON stream. `raw` lets a test send bytes that are
 * not one-object-per-line, to exercise the buffering of split lines.
 */
function serveStream(chunks: Array<object | string>, endpoint = ENDPOINT) {
  const seen: { body?: Record<string, unknown> } = {};
  server.use(
    http.post(endpoint, async ({ request }) => {
      seen.body = (await request.json()) as Record<string, unknown>;
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          for (const c of chunks) {
            controller.enqueue(
              encoder.encode(
                typeof c === "string" ? c : `${JSON.stringify(c)}\n`,
              ),
            );
          }
          controller.close();
        },
      });
      return new HttpResponse(stream, {
        headers: { "Content-Type": "application/x-ndjson" },
      });
    }),
  );
  return seen;
}

type StreamResult = Awaited<
  ReturnType<ReturnType<typeof useChatStreaming>["sendMessage"]>
>;

/**
 * Sends a message inside act() and returns the result.
 *
 * The holder object exists because assigning to a `let` from inside the act()
 * callback makes TypeScript narrow it to `never`.
 */
async function send(
  result: { current: ReturnType<typeof useChatStreaming> },
  options: Parameters<ReturnType<typeof useChatStreaming>["sendMessage"]>[0],
): Promise<StreamResult> {
  const holder: { value: StreamResult } = { value: null };
  await act(async () => {
    holder.value = await result.current.sendMessage(options);
  });
  return holder.value;
}

function setup(options: Parameters<typeof useChatStreaming>[0] = {}) {
  const onComplete = vi.fn();
  const onError = vi.fn();
  const rendered = renderHook(() =>
    useChatStreaming({ onComplete, onError, ...options }),
  );
  return { ...rendered, onComplete, onError };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

describe("useChatStreaming", () => {
  describe("request body", () => {
    it("always sends prompt, stream and the limit/threshold defaults", async () => {
      const seen = serveStream([textChunk("hi")]);
      const { result } = setup();

      await act(async () => {
        await result.current.sendMessage({ prompt: "hello" });
      });

      expect(seen.body).toEqual({
        prompt: "hello",
        stream: true,
        limit: 10,
        scoreThreshold: 0,
      });
    });

    it("includes the optional ids only when provided", async () => {
      const seen = serveStream([textChunk("hi")]);
      const { result } = setup();

      await act(async () => {
        await result.current.sendMessage({
          prompt: "hello",
          previousResponseId: "prev-1",
          conversationId: "conv-1",
          filter_id: "f-1",
          limit: 3,
          scoreThreshold: 0.5,
        });
      });

      expect(seen.body).toMatchObject({
        previous_response_id: "prev-1",
        conversation_id: "conv-1",
        filter_id: "f-1",
        limit: 3,
        scoreThreshold: 0.5,
      });
    });

    it("normalizes filters and omits them when nothing is selected", async () => {
      const withFilters = serveStream([textChunk("hi")]);
      const { result } = setup();

      await act(async () => {
        await result.current.sendMessage({
          prompt: "p",
          filters: { data_sources: ["s3"], owners: ["*"] },
        });
      });
      expect(withFilters.body?.filters).toEqual({ data_sources: ["s3"] });

      const empty = serveStream([textChunk("hi")]);
      await act(async () => {
        await result.current.sendMessage({
          prompt: "p",
          filters: { data_sources: ["*"] },
        });
      });
      expect(empty.body?.filters).toBeUndefined();
    });

    it("posts to a custom endpoint when configured", async () => {
      const seen = serveStream([textChunk("hi")], "/api/custom");
      const { result } = setup({ endpoint: "/api/custom" });

      await act(async () => {
        await result.current.sendMessage({ prompt: "p" });
      });

      expect(seen.body?.prompt).toBe("p");
    });
  });

  describe("streaming success", () => {
    it("accumulates deltas into one final message", async () => {
      serveStream([textChunk("Hel"), textChunk("lo "), textChunk("there")]);
      const { result, onComplete } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned).toMatchObject({
        role: "assistant",
        content: "Hello there",
        isStreaming: false,
      });
      expect(onComplete).toHaveBeenCalledOnce();
      expect(onComplete.mock.calls[0][0].content).toBe("Hello there");
    });

    it("reassembles a JSON object split across two network chunks", async () => {
      const line = JSON.stringify(textChunk("split"));
      serveStream([line.slice(0, 12), `${line.slice(12)}\n`]);
      const { result } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned?.content).toBe("split");
    });

    it("skips unparseable lines instead of failing the stream", async () => {
      serveStream(["not json at all\n", textChunk("good")]);
      const { result } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned?.content).toBe("good");
    });

    it("captures the response id from id or response_id", async () => {
      serveStream([{ id: "resp-1" }, textChunk("hi")]);
      const { result, onComplete } = setup();
      await act(async () => {
        await result.current.sendMessage({ prompt: "p" });
      });
      expect(onComplete.mock.calls[0][1]).toBe("resp-1");

      serveStream([{ response_id: "resp-2" }, textChunk("hi")]);
      await act(async () => {
        await result.current.sendMessage({ prompt: "p" });
      });
      expect(onComplete.mock.calls[1][1]).toBe("resp-2");
    });

    it("reads OpenRAG output_text chunks (#1534)", async () => {
      serveStream([{ output_text: "watsonx says hi" }]);
      const { result } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned?.content).toBe("watsonx says hi");
    });

    it("clears the streaming message and refreshes history when done", async () => {
      serveStream([textChunk("hi")]);
      const { result } = setup();

      await act(async () => {
        await result.current.sendMessage({ prompt: "p" });
      });

      await waitFor(() => expect(result.current.streamingMessage).toBeNull());
      expect(result.current.isLoading).toBe(false);
      expect(refreshConversations).toHaveBeenCalledWith(true);
    });
  });

  describe("errors", () => {
    it("reports a non-OK response with its status and body (#859)", async () => {
      server.use(
        http.post(ENDPOINT, () =>
          HttpResponse.text("upstream exploded", { status: 502 }),
        ),
      );
      const { result, onError, onComplete } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned?.error).toBe(true);
      expect(returned?.content).toContain("upstream exploded");
      expect(onError).toHaveBeenCalledOnce();
      // onComplete still fires so the failed turn is appended to history.
      expect(onComplete).toHaveBeenCalledOnce();
      expect(onComplete.mock.calls[0][0].error).toBe(true);
    });

    it("reports an empty stream as no response received", async () => {
      serveStream([]);
      const { result } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned?.content).toBe(
        "The server didn't return a response. Please try again.",
      );
    });

    it("surfaces a provider error carried in the stream (#2127)", async () => {
      serveStream([
        textChunk("partial answer"),
        { finish_reason: "error", error: "Invalid API key for watsonx" },
      ]);
      const { result } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned?.error).toBe(true);
      expect(returned?.content).toContain("Invalid API key");
    });

    it("keeps a benign partial answer above the error text (#2127)", async () => {
      serveStream([
        textChunk("The capital is Paris."),
        { finish_reason: "error", error: "connection reset" },
      ]);
      const { result } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned?.content).toContain("The capital is Paris.");
      expect(returned?.content).toContain("connection reset");
    });

    it("does not prepend a partial that is itself a provider dump (#2127)", async () => {
      serveStream([
        textChunk("Error: invalid api key for provider"),
        { finish_reason: "error", error: "Authentication failed" },
      ]);
      const { result } = setup();

      const returned = await send(result, { prompt: "p" });

      // Content starting with "Error:" trips looksLikeProviderErrorContent
      // (chat-stream-errors.ts:107), so the thrown message IS the content. The
      // guard being pinned here is that it is not ALSO prepended as a partial,
      // which would show the same text twice.
      const occurrences =
        returned?.content?.match(/invalid api key for provider/g)?.length ?? 0;
      expect(occurrences).toBe(1);
    });

    it("treats accumulated content that looks like a provider error as one", async () => {
      serveStream([textChunk('{"error": {"message": "Rate limit exceeded"}}')]);
      const { result } = setup();

      const returned = await send(result, { prompt: "p" });

      expect(returned?.error).toBe(true);
      expect(returned?.content).not.toContain("{");
    });

    it("stops loading after an error", async () => {
      server.use(
        http.post(ENDPOINT, () => HttpResponse.text("nope", { status: 500 })),
      );
      const { result } = setup();

      await act(async () => {
        await result.current.sendMessage({ prompt: "p" });
      });

      expect(result.current.isLoading).toBe(false);
      expect(result.current.streamingMessage).toBeNull();
    });
  });

  describe("abortStream", () => {
    it("clears streaming state immediately", async () => {
      const { result } = setup();

      act(() => {
        result.current.abortStream();
      });

      expect(result.current.isLoading).toBe(false);
      expect(result.current.streamingMessage).toBeNull();
    });

    // NOT TESTED HERE, ON PURPOSE: aborting a stream that is still open.
    //
    // It needs a handler that holds the response open, then an abort at just
    // the right moment. Under MSW the reader's pending read() does not settle
    // when the controller aborts, so the test hangs until the suite timeout.
    // Making it pass would mean sleeping on wall-clock timing — precisely the
    // flakiness this fast layer exists to avoid.
    //
    // Mid-stream abort is a real user action (clicking stop), so it belongs in
    // Playwright against a real server. What is checkable here — that
    // abortStream clears state synchronously — is covered above.
  });
});
