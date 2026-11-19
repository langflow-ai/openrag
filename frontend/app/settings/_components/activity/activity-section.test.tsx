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
    // The summary loads independently of the list, so wait for it too.
    expect((await screen.findByText("Positive")).nextSibling).toHaveTextContent(
      "—",
    );
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

  it("offers a retry when only the summary fails", async () => {
    let fail = true;
    render([
      http.get("/api/activity/feedback/summary", () =>
        fail
          ? HttpResponse.json({ detail: "x" }, { status: 500 })
          : HttpResponse.json({
              up: 1,
              down: 0,
              total: 1,
              positive_percentage: 100,
            }),
      ),
      http.get("/api/activity/feedback", () =>
        HttpResponse.json({
          items: [feedbackItem("f1", "up")],
          next_cursor: null,
        }),
      ),
    ]);
    fireEvent.click(
      await screen.findByRole("button", { name: /^retry summary$/i }),
    );
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /^retry summary$/i }));
    expect(await screen.findByText("100%")).toBeInTheDocument();
    // The list was unaffected and stays visible.
    expect(screen.getAllByText("Thumbs up").length).toBeGreaterThan(0);
  });

  it("keeps loaded rows and offers retry when a later page fails", async () => {
    let pageTwoAttempts = 0;
    render([
      summary(),
      http.get("/api/activity/feedback", ({ request }) => {
        if (!new URL(request.url).searchParams.get("cursor")) {
          return HttpResponse.json({
            items: [feedbackItem("f1", "up")],
            next_cursor: "C",
          });
        }
        pageTwoAttempts += 1;
        // Fail the first attempt at page two only, then succeed.
        return pageTwoAttempts === 1
          ? HttpResponse.json({ detail: "x" }, { status: 500 })
          : HttpResponse.json({
              items: [feedbackItem("f2", "up")],
              next_cursor: null,
            });
      }),
    ]);
    fireEvent.click(
      await screen.findByRole("button", { name: /^load more$/i }),
    );
    const retry = await screen.findByRole("button", {
      name: /^retry loading more$/i,
    });
    // The first page is still on screen next to the error.
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    fireEvent.click(retry);
    await waitFor(() =>
      expect(screen.getAllByRole("listitem")).toHaveLength(2),
    );
    expect(
      screen.queryByRole("button", { name: /^retry loading more$/i }),
    ).not.toBeInTheDocument();
  });

  it("retries a failed refresh with refetch, and a failed next page with fetchNextPage", async () => {
    const cursors: Array<string | null> = [];
    let failNext = 0;
    const { queryClient } = renderWithProviders(<ActivitySection />, {
      providers: ["auth"],
      auth: authPresets.admin,
      handlers: [
        summary(),
        http.get("/api/activity/feedback", ({ request }) => {
          const cursor = new URL(request.url).searchParams.get("cursor");
          cursors.push(cursor);
          if (failNext > 0) {
            failNext -= 1;
            return HttpResponse.json({ detail: "x" }, { status: 500 });
          }
          return HttpResponse.json({
            items: [feedbackItem(cursor ? "f2" : "f1", "up")],
            next_cursor: cursor ? null : "C",
          });
        }),
      ],
    });
    await screen.findAllByRole("listitem");

    // 1. A background refresh fails while page one is on screen.
    failNext = 1;
    await queryClient.refetchQueries({ queryKey: ["activity"] });
    const refresh = await screen.findByRole("button", {
      name: /^retry refresh$/i,
    });
    expect(
      screen.queryByRole("button", { name: /retry loading more/i }),
    ).toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    cursors.length = 0;
    fireEvent.click(refresh);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /^retry refresh$/i }),
      ).toBeNull(),
    );
    // The retry re-requested page one (no cursor), it did not paginate.
    expect(cursors[0]).toBeNull();
  });
});
