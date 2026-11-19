import { fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets, withAuth } from "@/test-utils/fixtures/auth";
import { renderWithProviders } from "@/test-utils/render";
import { ActivitySection } from "./activity-section";

const feedbackItem = (id: string, rating: "up" | "down", comment = "") => ({
  id,
  message_id: `m-${id}`,
  conversation_id: "c1",
  user_id: "u1",
  rating,
  comment: comment || null,
  model_provider: "openai",
  model: "gpt",
  created_at: "2026-01-02T03:04:05+00:00",
  updated_at: "2026-01-02T03:04:05+00:00",
});

function render(
  handlers: Parameters<typeof renderWithProviders>[1] extends infer O
    ? NonNullable<O> extends { handlers?: infer H }
      ? H
      : never
    : never,
  auth = authPresets.admin,
) {
  return renderWithProviders(<ActivitySection />, {
    providers: ["auth"],
    auth,
    handlers,
  });
}

const summary = (over = {}) =>
  http.get("/api/activity/feedback/summary", () =>
    HttpResponse.json({
      up: 3,
      down: 1,
      total: 4,
      positive_percentage: 75,
      ...over,
    }),
  );

describe("ActivitySection", () => {
  it("shows an unavailable state without server-reported access", async () => {
    render(
      [],
      withAuth(authPresets.admin, { usersMe: { activity_access: false } }),
    );
    expect(
      await screen.findByText(/activity is unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Audit" }),
    ).not.toBeInTheDocument();
  });

  it("denies when RBAC is disabled even though permissions look complete", async () => {
    render([], authPresets.rbacDisabled);
    expect(
      await screen.findByText(/activity is unavailable/i),
    ).toBeInTheDocument();
  });

  it("renders summary and comments as escaped text", async () => {
    render([
      summary(),
      http.get("/api/activity/feedback", () =>
        HttpResponse.json({
          items: [feedbackItem("f1", "down", "<img src=x onerror=alert(1)>")],
          next_cursor: null,
        }),
      ),
    ]);
    expect(await screen.findByText("75%")).toBeInTheDocument();
    expect(screen.getByText("Total votes").nextSibling).toHaveTextContent("4");
    expect(
      await screen.findByText("<img src=x onerror=alert(1)>"),
    ).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("2026-01-02 03:04:05 UTC")).toBeInTheDocument();
  });

  it("shows a dash for an empty denominator and an empty state", async () => {
    render([
      summary({ up: 0, down: 0, total: 0, positive_percentage: null }),
      http.get("/api/activity/feedback", () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    ]);
    expect(await screen.findByText(/no feedback matches/i)).toBeInTheDocument();
    expect(screen.getByText("Positive").nextSibling).toHaveTextContent("—");
  });

  it("filters by rating and paginates with the server cursor", async () => {
    const seen: URL[] = [];
    render([
      summary(),
      http.get("/api/activity/feedback", ({ request }) => {
        const url = new URL(request.url);
        seen.push(url);
        const cursor = url.searchParams.get("cursor");
        return HttpResponse.json(
          cursor
            ? { items: [feedbackItem("f2", "up")], next_cursor: null }
            : { items: [feedbackItem("f1", "up")], next_cursor: "CUR1" },
        );
      }),
    ]);
    fireEvent.click(
      await screen.findByRole("button", { name: /^load more$/i }),
    );
    await waitFor(() =>
      expect(screen.getAllByText("Thumbs up").length).toBeGreaterThan(1),
    );
    expect(seen[1].searchParams.get("cursor")).toBe("CUR1");
    fireEvent.change(screen.getByLabelText("Rating"), {
      target: { value: "down" },
    });
    await waitFor(() =>
      expect(seen.at(-1)?.searchParams.get("rating")).toBe("down"),
    );
    // new filters restart pagination: no stale cursor
    expect(seen.at(-1)?.searchParams.get("cursor")).toBeNull();
  });

  it("shows an error with retry when loading fails", async () => {
    let fail = true;
    render([
      summary(),
      http.get("/api/activity/feedback", () =>
        fail
          ? HttpResponse.json({ detail: "x" }, { status: 500 })
          : HttpResponse.json({ items: [], next_cursor: null }),
      ),
    ]);
    expect(
      await screen.findByText(/failed to load activity/i),
    ).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /^retry$/i }));
    expect(await screen.findByText(/no feedback matches/i)).toBeInTheDocument();
  });

  it("shows a denied message when the server returns 403", async () => {
    render([
      http.get("/api/activity/feedback/summary", () =>
        HttpResponse.json({ detail: {} }, { status: 403 }),
      ),
      http.get("/api/activity/feedback", () =>
        HttpResponse.json({ detail: {} }, { status: 403 }),
      ),
    ]);
    expect(
      (await screen.findAllByText(/do not have access/i)).length,
    ).toBeGreaterThan(0);
  });
});
