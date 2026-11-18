import { act, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders } from "@/test-utils/render";
import { useChatStreaming } from "./useChatStreaming";

function stream(lines: object[]) {
  const text = lines.map((l) => `${JSON.stringify(l)}\n`).join("");
  return new HttpResponse(text, {
    headers: { "Content-Type": "text/event-stream" },
  });
}

function Harness({ onComplete }: { onComplete: (m: unknown) => void }) {
  const { sendMessage } = useChatStreaming({
    endpoint: "/api/chat",
    onComplete,
  });
  return (
    <button type="button" onClick={() => sendMessage({ prompt: "hi" })}>
      go
    </button>
  );
}

async function run(lines: object[]) {
  const onComplete = vi.fn();
  const { getByRole } = renderWithProviders(
    <Harness onComplete={onComplete} />,
    {
      providers: ["auth", "chat"],
      auth: authPresets.admin,
      handlers: [http.post("/api/chat", () => stream(lines))],
    },
  );
  await act(async () => {
    getByRole("button", { name: "go" }).click();
  });
  await waitFor(() => expect(onComplete).toHaveBeenCalled());
  return onComplete.mock.calls[0][0] as { messageId?: string };
}

const delta = {
  id: "c1",
  object: "response.chunk",
  delta: { content: "Hello" },
};

describe("useChatStreaming message ids", () => {
  it("attaches the id advertised on the final event", async () => {
    const msg = await run([
      delta,
      {
        id: "c1",
        status: "completed",
        finish_reason: "stop",
        delta: {},
        message_id: "m1",
      },
      {
        response: { id: "c1", message_id: "m1" },
        type: "response.completed",
        message_id: "m1",
      },
    ]);
    expect(msg.messageId).toBe("m1");
  });

  it("leaves the id unset when persistence failed (none advertised)", async () => {
    const msg = await run([
      delta,
      { id: "c1", status: "completed", finish_reason: "stop", delta: {} },
    ]);
    expect(msg.messageId).toBeUndefined();
  });
});
