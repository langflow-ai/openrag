import { fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders } from "@/test-utils/render";
import MessageActions from "./message-actions";

const saved = (rating: "up" | "down", comment: string | null) => ({
  message_id: "m1",
  rating,
  comment,
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
});

function setup(
  props: Partial<React.ComponentProps<typeof MessageActions>> = {},
  handler?: Parameters<typeof http.post>[1],
) {
  const bodies: unknown[] = [];
  const track = vi.fn();
  const utils = renderWithProviders(
    <MessageActions
      trackFeedback={track}
      conversationId="c1"
      messageId="m1"
      {...props}
    />,
    {
      providers: ["auth"],
      auth: authPresets.admin,
      handlers: [
        http.post(
          "/api/chat/c1/messages/m1/feedback",
          handler ??
            (async ({ request }) => {
              const body = (await request.json()) as {
                rating: "up" | "down";
                comment: string | null;
              };
              bodies.push(body);
              return HttpResponse.json(saved(body.rating, body.comment));
            }),
        ),
      ],
    },
  );
  return { ...utils, bodies, track };
}

describe("MessageActions", () => {
  it("renders nothing without a durable message id", () => {
    const { container } = setup({ messageId: undefined });
    expect(container).toBeEmptyDOMElement();
  });

  it("persists a thumbs-up with a null comment and shows it selected", async () => {
    const { bodies, track } = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Like" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Like" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(bodies).toEqual([{ rating: "up", comment: null }]);
    expect(track).toHaveBeenCalledWith("like");
    // Analytics receives only the rating, never a comment.
    expect(track.mock.calls.flat()).toEqual(["like"]);
  });

  it("restores the persisted selection from history", async () => {
    setup({ feedback: { rating: "down", comment: "meh" } });
    expect(
      await screen.findByRole("button", { name: "Dislike" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("does not resubmit the already selected rating", async () => {
    const { bodies } = setup({ feedback: { rating: "up", comment: null } });
    fireEvent.click(await screen.findByRole("button", { name: "Like" }));
    expect(bodies).toEqual([]);
  });

  it("thumbs-down opens an optional comment; saving sends the full value", async () => {
    const { bodies } = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Dislike" }));
    const box = await screen.findByLabelText("Feedback comment");
    fireEvent.change(box, { target: { value: "wrong source" } });
    fireEvent.click(screen.getByRole("button", { name: /^save comment$/i }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[0]).toEqual({ rating: "down", comment: null });
    expect(bodies[1]).toEqual({ rating: "down", comment: "wrong source" });
  });

  it("cancelling the comment keeps the recorded vote", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Dislike" }));
    fireEvent.click(await screen.findByRole("button", { name: /^cancel$/i }));
    expect(screen.queryByLabelText("Feedback comment")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dislike" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("switching rating preserves an existing comment", async () => {
    const { bodies } = setup({ feedback: { rating: "up", comment: "good" } });
    fireEvent.click(await screen.findByRole("button", { name: "Dislike" }));
    await waitFor(() =>
      expect(bodies[0]).toEqual({ rating: "down", comment: "good" }),
    );
  });

  it("keeps the prior selection on error and retries", async () => {
    let calls = 0;
    setup({ feedback: { rating: "up", comment: null } }, () => {
      calls += 1;
      return calls === 1
        ? HttpResponse.json({ detail: "boom" }, { status: 500 })
        : HttpResponse.json(saved("down", null));
    });
    fireEvent.click(await screen.findByRole("button", { name: "Dislike" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /couldn.t save/i,
    );
    expect(screen.getByRole("button", { name: "Like" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: /^retry$/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Dislike" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
  });

  it("blocks duplicate in-flight submissions", async () => {
    let calls = 0;
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => {
      release = r;
    });
    setup({}, async () => {
      calls += 1;
      await gate;
      return HttpResponse.json(saved("up", null));
    });
    const like = await screen.findByRole("button", { name: "Like" });
    fireEvent.click(like);
    await screen.findByRole("status");
    expect(like).toBeDisabled();
    fireEvent.click(like);
    release();
    await waitFor(() => expect(like).toHaveAttribute("aria-pressed", "true"));
    expect(calls).toBe(1);
  });
});
