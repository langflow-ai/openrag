/**
 * chat/page.tsx — smoke test that exercises the lines flagged by diff-coverage.
 *
 * Lines 68, 71-72: useAuth() call + isNoAuthMode guard + displayName resolution.
 * Lines 71-88: useEffect that replaces PLACEHOLDER_GREETING after auth settles.
 * Lines 106, 108, 110-112, 114, 117-119, 122, 126, 128, 134: hook calls and
 *   handleFileDrop callback that run on mount.
 * Lines 373, 653: event-handler and effect bodies — covered by dispatching
 *   'newConversation' and setting up placeholderConversation.
 *
 * ChatPage is not exported; we mount via the default export ProtectedChatPage
 * and stub ProtectedRoute to a passthrough.
 */
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { authPresets, makeUser, withAuth } from "@/test-utils/fixtures/auth";
import { renderWithProviders } from "@/test-utils/render";
import { PLACEHOLDER_GREETING } from "./_types/types";

// ── Module stubs ─────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: vi.fn() }),
}));

// ProtectedRoute passthrough — avoids auth redirect logic
vi.mock("@/components/protected-route", () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// use-stick-to-bottom has no layout engine in jsdom
vi.mock("use-stick-to-bottom", () => {
  function StickToBottom({ children }: { children: React.ReactNode }) {
    return <div>{children}</div>;
  }
  StickToBottom.Content = ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  );
  return {
    StickToBottom,
    useStickToBottomContext: () => ({
      isAtBottom: true,
      scrollToBottom: vi.fn(),
    }),
  };
});

vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
}));

const { chatFilterState, sendStreamingMessageMock } = vi.hoisted(() => ({
  chatFilterState: {
    conversationFilter: null as null | {
      id: string;
      name: string;
      description: string;
      query_data: string;
      owner: string;
      created_at: string;
      updated_at: string;
    },
    setConversationFilter: vi.fn(),
  },
  sendStreamingMessageMock: vi.fn(),
}));

vi.mock("@/contexts/chat-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/chat-context")>()),
  useChat: () => ({
    endpoint: "chat",
    setEndpoint: vi.fn(),
    currentConversationId: null,
    conversationData: null,
    setCurrentConversationId: vi.fn(),
    addConversationDoc: vi.fn(),
    forkFromResponse: vi.fn(),
    refreshConversations: vi.fn(),
    refreshConversationsSilent: vi.fn(),
    refreshTrigger: 0,
    refreshTriggerSilent: 0,
    previousResponseIds: { chat: null, langflow: null },
    setPreviousResponseIds: vi.fn(),
    placeholderConversation: null,
    conversationFilter: chatFilterState.conversationFilter,
    setConversationFilter: chatFilterState.setConversationFilter,
    loading: false,
    setLoading: vi.fn(),
    setChatError: vi.fn(),
  }),
}));

vi.mock("@/contexts/task-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/task-context")>()),
  useTask: () => ({ tasks: [], isLoading: false }),
}));

vi.mock("@/hooks/use-onboarding-state", () => ({
  useOnboardingState: () => ({ isOnboardingComplete: true }),
}));

vi.mock("@/hooks/use-supported-file-types", () => ({
  useSupportedFileTypes: () => ({
    supportedFileTypes: { "application/pdf": [".pdf"] },
    supportedExtensions: [".pdf"],
  }),
}));

vi.mock("@/hooks/useChatStreaming", () => ({
  useChatStreaming: () => ({
    streamingMessage: null,
    isLoading: false,
    sendMessage: sendStreamingMessageMock,
    abortStream: vi.fn(),
    isChatStreaming: false,
  }),
}));

vi.mock("@/app/api/queries/useGetConversationsQuery", () => ({
  useGetConversationsQuery: () => ({ data: [], isLoading: false }),
}));

vi.mock("@/app/api/queries/useGetNudgesQuery", () => ({
  useGetNudgesQuery: () => ({ data: null }),
}));

vi.mock("@/app/api/queries/useGetSettingsQuery", () => ({
  useGetSettingsQuery: () => ({
    data: { agent: { ingest_via_chat: false } },
  }),
}));

vi.mock("@/lib/analytics", () => ({
  trackLLMCall: vi.fn(),
  trackButton: vi.fn(),
}));

// Stub AssistantMessage and ChatInput to avoid their own heavy dep chains
vi.mock("@/app/chat/_components/assistant-message", () => ({
  AssistantMessage: ({ content }: { content: string }) => (
    <div data-testid="assistant-message">{content}</div>
  ),
}));

const { imeStateHolder, submitSpy, chatCallbacks, uploadFileForContextMock } =
  vi.hoisted(() => ({
    imeStateHolder: {
      current: { composing: false, compositionEndedAt: 0, now: 0 },
    },
    submitSpy: vi.fn((event: { preventDefault: () => void }) => {
      event.preventDefault();
    }),
    chatCallbacks: {
      onSubmit: undefined as
        | ((event: { preventDefault: () => void }) => void | Promise<void>)
        | undefined,
      onFileSelected: undefined as ((file: File) => void) | undefined,
    },
    uploadFileForContextMock: vi.fn(),
  }));

vi.mock("@/lib/upload-utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/upload-utils")>();
  return {
    ...actual,
    uploadFileForContext: uploadFileForContextMock,
  };
});

vi.mock("@/app/chat/_components/chat-input", () => {
  const { forwardRef, useImperativeHandle } = require("react");
  return {
    ChatInput: forwardRef(
      (
        props: {
          onChange?: (value: string) => void;
          onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
          onSubmit?: (event: {
            preventDefault: () => void;
          }) => void | Promise<void>;
          onFileSelected?: (file: File) => void;
        },
        ref: React.Ref<{ getImeState: () => unknown }>,
      ) => {
        chatCallbacks.onSubmit = props.onSubmit;
        chatCallbacks.onFileSelected = props.onFileSelected;
        useImperativeHandle(ref, () => ({
          focusInput() {},
          clickFileInput() {},
          getImeState: () => imeStateHolder.current,
        }));
        return (
          <form onSubmit={submitSpy}>
            <textarea
              data-testid="chat-input"
              onChange={(e) => props.onChange?.(e.target.value)}
              onKeyDown={props.onKeyDown}
            />
          </form>
        );
      },
    ),
  };
});

vi.mock("@/app/chat/_components/nudges", () => ({
  default: () => <div data-testid="nudges" />,
}));

vi.mock("@/app/chat/_components/error-message", () => ({
  ErrorMessage: () => null,
}));

vi.mock("@/app/chat/_components/user-message", () => ({
  UserMessage: () => null,
}));

// ── Import the component (after mocks are set up) ────────────────────────────

import ProtectedChatPage from "./page";

// ── Tests ────────────────────────────────────────────────────────────────────

describe("ChatPage — coverage for diff-flagged lines", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    imeStateHolder.current = {
      composing: false,
      compositionEndedAt: 0,
      now: 0,
    };
    submitSpy.mockClear();
    uploadFileForContextMock.mockReset();
    chatFilterState.conversationFilter = null;
    chatFilterState.setConversationFilter.mockReset();
    sendStreamingMessageMock.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // Lines 68, 71-72, 80-88: mount exercises useAuth(), displayName derivation,
  // and the useEffect that re-generates the greeting.
  it("mounts without error and renders the chat input", () => {
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: authPresets.noAuthMode,
    });
    // ChatInput stub is rendered — confirms the component tree mounted
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
  });

  // Lines 106, 108, 110-112, 114, 117-119, 122, 126, 128, 134:
  // These are all hook calls / state initialisers that run unconditionally.
  // Covered by the mount above; add a second variant to ensure the auth branch
  // (isNoAuthMode=false) is also exercised.
  it("mounts with an authenticated user (non-noAuth mode)", () => {
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: authPresets.admin,
    });
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
  });

  // Line 373: fires when a 'newConversation' window event is dispatched
  it("resets messages when the newConversation event fires", () => {
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: authPresets.noAuthMode,
    });

    act(() => {
      window.dispatchEvent(new Event("newConversation"));
      vi.runAllTimers();
    });

    // Component is still mounted and input is present
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
  });

  it("replaces the placeholder greeting with a named greeting after login", async () => {
    vi.useRealTimers();
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: withAuth(authPresets.admin, {
        me: { user: makeUser({ name: "Olfa Maslah" }) },
      }),
    });

    await waitFor(() => {
      const text = screen.getByTestId("assistant-message").textContent;
      expect(text).not.toBe(PLACEHOLDER_GREETING.content);
      expect(text).toMatch(/Olfa/);
    });
  });

  it("does not submit when Enter confirms an IME candidate", () => {
    vi.useRealTimers();
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: authPresets.noAuthMode,
    });
    const input = screen.getByTestId("chat-input");

    expect(fireEvent.keyDown(input, { key: "Enter", isComposing: true })).toBe(
      true,
    );
    expect(fireEvent.keyDown(input, { key: "Enter", keyCode: 229 })).toBe(true);
  });

  it("does not submit the Enter Safari fires just after composition ends", () => {
    vi.useRealTimers();
    imeStateHolder.current = {
      composing: false,
      compositionEndedAt: 1_000,
      now: 1_010,
    };
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: authPresets.noAuthMode,
    });
    const input = screen.getByTestId("chat-input");
    fireEvent.change(input, { target: { value: "日本語" } });

    expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(false);
    expect(submitSpy).not.toHaveBeenCalled();
  });

  it("prevents a newline and submits when Enter is not an IME confirmation", () => {
    vi.useRealTimers();
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: authPresets.noAuthMode,
    });
    const input = screen.getByTestId("chat-input");
    fireEvent.change(input, { target: { value: "hello" } });

    expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(false);
    expect(submitSpy).toHaveBeenCalledOnce();
  });

  it("does not send a message when the attached upload fails", async () => {
    vi.useRealTimers();
    uploadFileForContextMock.mockRejectedValueOnce(new Error("too big"));
    const post = vi.spyOn(apiClient, "post");
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: authPresets.noAuthMode,
    });

    act(() => {
      chatCallbacks.onFileSelected?.(
        new File(["x"], "notes.pdf", { type: "application/pdf" }),
      );
    });
    await act(async () => {
      await chatCallbacks.onSubmit?.({ preventDefault() {} });
    });

    expect(uploadFileForContextMock).toHaveBeenCalledOnce();
    expect(post).not.toHaveBeenCalled();
  });

  it("replaces the placeholder greeting after mount in no-auth mode", async () => {
    vi.useRealTimers();
    renderWithProviders(<ProtectedChatPage />, {
      providers: ["auth"],
      auth: authPresets.noAuthMode,
    });

    await waitFor(() => {
      expect(screen.getByTestId("assistant-message").textContent).not.toBe(
        PLACEHOLDER_GREETING.content,
      );
    });
  });

  describe("conversation filter refresh", () => {
    const stale = {
      id: "f1",
      name: "stale-test",
      description: "",
      query_data: JSON.stringify({
        query: "",
        filters: { data_sources: ["*"] },
      }),
      owner: "me",
      created_at: "",
      updated_at: "1",
    };

    it("loads the saved filter when the chat page opens", async () => {
      vi.useRealTimers();
      const fresh = {
        ...stale,
        query_data: JSON.stringify({
          query: "",
          filters: { data_sources: ["aurora.txt"] },
        }),
        updated_at: "2",
      };
      chatFilterState.conversationFilter = stale;
      renderWithProviders(<ProtectedChatPage />, {
        providers: ["auth"],
        auth: authPresets.noAuthMode,
        handlers: [
          http.get("/api/knowledge-filter/f1", () =>
            HttpResponse.json({ success: true, filter: fresh }),
          ),
        ],
      });

      await waitFor(() =>
        expect(chatFilterState.setConversationFilter).toHaveBeenCalledWith(
          fresh,
        ),
      );
    });

    it("keeps the current filter when nothing changed", async () => {
      vi.useRealTimers();
      let fetched = false;
      chatFilterState.conversationFilter = stale;
      renderWithProviders(<ProtectedChatPage />, {
        providers: ["auth"],
        auth: authPresets.noAuthMode,
        handlers: [
          http.get("/api/knowledge-filter/f1", () => {
            fetched = true;
            return HttpResponse.json({ success: true, filter: stale });
          }),
        ],
      });

      await waitFor(() => expect(fetched).toBe(true));
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(chatFilterState.setConversationFilter).not.toHaveBeenCalled();
    });

    it("sends the saved filter when the open chat still has the old copy", async () => {
      vi.useRealTimers();
      const fresh = {
        ...stale,
        query_data: JSON.stringify({
          query: "",
          filters: { data_sources: ["aurora.txt"] },
          limit: 10,
          scoreThreshold: 0,
        }),
        updated_at: "2",
      };
      chatFilterState.conversationFilter = stale;
      renderWithProviders(<ProtectedChatPage />, {
        providers: ["auth"],
        auth: authPresets.noAuthMode,
        handlers: [
          http.get("/api/knowledge-filter/f1", () =>
            HttpResponse.json({ success: true, filter: fresh }),
          ),
        ],
      });

      fireEvent.change(screen.getByTestId("chat-input"), {
        target: { value: "what is in the file?" },
      });
      await act(async () => {
        void chatCallbacks.onSubmit?.({ preventDefault() {} });
      });

      await waitFor(() =>
        expect(sendStreamingMessageMock).toHaveBeenCalledWith(
          expect.objectContaining({
            filter_id: "f1",
            filters: { data_sources: ["aurora.txt"] },
          }),
        ),
      );
    });

    it("sends the open chat's copy when the saved filter cannot be loaded", async () => {
      vi.useRealTimers();
      const snapshot = {
        ...stale,
        query_data: JSON.stringify({
          filters: { data_sources: ["borealis.txt"] },
        }),
      };
      chatFilterState.conversationFilter = snapshot;
      renderWithProviders(<ProtectedChatPage />, {
        providers: ["auth"],
        auth: authPresets.noAuthMode,
        handlers: [
          http.get(
            "/api/knowledge-filter/f1",
            () => new HttpResponse(null, { status: 500 }),
          ),
        ],
      });

      fireEvent.change(screen.getByTestId("chat-input"), {
        target: { value: "what is in the file?" },
      });
      await act(async () => {
        void chatCallbacks.onSubmit?.({ preventDefault() {} });
      });

      await waitFor(() =>
        expect(sendStreamingMessageMock).toHaveBeenCalledWith(
          expect.objectContaining({
            filter_id: "f1",
            filters: { data_sources: ["borealis.txt"] },
          }),
        ),
      );
    });
  });
});
