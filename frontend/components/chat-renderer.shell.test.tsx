/**
 * Regression coverage for #2416: the authenticated app shell crashed with
 * "Maximum update depth exceeded" right after onboarding completed.
 *
 * Unlike chat-renderer.test.tsx, this mounts the REAL ChatProvider and the
 * REAL Navigation, so Navigation's auto-load effect and the chat context state
 * it writes can feed back into each other the way they do in the app.
 */
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useChat } from "@/contexts/chat-context";
import { authPresets } from "@/test-utils/fixtures/auth";
import {
  makeOnboardingSettings,
  makeSettings,
} from "@/test-utils/fixtures/settings";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import { setMockLocation } from "@/test-utils/router";
import { ChatRenderer } from "./chat-renderer";

vi.mock("@/lib/analytics", () => ({ page: vi.fn() }));

vi.mock("@/hooks/use-narrow-layout", () => ({
  useNarrowLayout: () => false,
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: () => true,
    canAny: () => true,
    isLoading: false,
    isPending: false,
    rbacEnforced: false,
  }),
}));

vi.mock("@/contexts/sidebar-overlay-context", () => ({
  useSidebarOverlay: () => ({
    isVisible: false,
    isPinned: false,
    isCollapsed: false,
    show: vi.fn(),
    hide: vi.fn(),
    hideNow: vi.fn(),
    pin: vi.fn(),
    unpin: vi.fn(),
    expand: vi.fn(),
    collapse: vi.fn(),
  }),
}));

// Far above what a healthy mount needs, far below where a loop would exhaust
// the heap (on a regression the loop otherwise runs until the worker OOMs).
const MAX_RENDERS = 200;
let chatRenders = 0;

/** Re-renders whenever the chat context value changes, like Header does. */
function ChatContextRenderCounter() {
  useChat();
  chatRenders += 1;
  if (chatRenders > MAX_RENDERS) {
    throw new Error(`Chat context did not settle after ${MAX_RENDERS} renders`);
  }
  return null;
}

describe("ChatRenderer shell (real ChatProvider + Navigation)", () => {
  beforeEach(() => {
    chatRenders = 0;
    setMockLocation({ pathname: "/chat" });
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("settles when the shell mounts before the conversations query is enabled", async () => {
    const errorSpy = vi.spyOn(console, "error");

    // The onboarding-to-shell transition: ChatRenderer already holds a
    // completed step, so it shows the layout and mounts Navigation, but the
    // settings ChatProvider reads have not caught up yet. The conversations
    // query is therefore still disabled and returns no data.
    renderWithProviders(
      <>
        <ChatContextRenderCounter />
        <ChatRenderer settings={makeSettings()}>
          <div>chat page</div>
        </ChatRenderer>
      </>,
      {
        providers: ["auth", "brand", "chat", "knowledgeFilter"],
        auth: authPresets.admin,
        handlers: [
          http.get("/api/settings", () =>
            HttpResponse.json(makeOnboardingSettings(3)),
          ),
          http.post("/api/knowledge-filter/search", () =>
            HttpResponse.json({ success: true, filters: [] }),
          ),
        ],
      },
    );

    expect(await screen.findByText("chat page")).toBeInTheDocument();
    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();

    // Once providers have resolved, the chat context must stop changing.
    let settled = -1;
    await waitFor(
      () => {
        const previous = settled;
        settled = chatRenders;
        expect(settled).toBe(previous);
      },
      { interval: 50 },
    );
    expect(chatRenders).toBeLessThan(MAX_RENDERS);

    const loopErrors = errorSpy.mock.calls.filter((args) =>
      args.some((arg) => /Maximum update depth/i.test(String(arg))),
    );
    expect(loopErrors).toEqual([]);
  });
});
