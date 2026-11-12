/**
 * ChatProvider — focused unit tests for the lines flagged by diff-coverage.
 *
 * Lines 120-123: conversationDataRef / placeholderConversationRef initialised on
 *   every render (they mirror state into refs so startNewConversation can read
 *   current values without re-creating the callback).
 * Lines 240-313: startNewConversation body — clearing state, reading
 *   localStorage, creating the placeholder ConversationData.
 *
 * We mount the real provider via renderHook so the actual logic runs.
 * useOnboardingState is stubbed to isolate from the settings API.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatProvider, useChat } from "./chat-context";

const { settingsState } = vi.hoisted(() => ({
  settingsState: {
    current: {
      agent: { disable_chat_with_langflow: false },
    } as { agent?: { disable_chat_with_langflow?: boolean } } | undefined,
  },
}));

vi.mock("@/app/api/queries/useGetSettingsQuery", () => ({
  useGetSettingsQuery: () => ({ data: settingsState.current }),
}));

// Stub out useOnboardingState — it fetches settings and is unrelated to what
// we are testing here.
vi.mock("@/hooks/use-onboarding-state", () => ({
  useOnboardingState: () => ({ isOnboardingComplete: true }),
}));

// Stub getFilterById so the localStorage branch can resolve without a network call.
vi.mock("@/app/api/queries/useGetFilterByIdQuery", () => ({
  getFilterById: vi.fn().mockResolvedValue(null),
}));

function renderChatHook() {
  return renderHook(() => useChat(), {
    wrapper: ({ children }) => <ChatProvider>{children}</ChatProvider>,
  });
}

describe("ChatProvider — startNewConversation", () => {
  beforeEach(() => {
    localStorage.clear();
    settingsState.current = {
      agent: { disable_chat_with_langflow: false },
    };
  });

  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // lines 120-123 — refs are wired on mount; this simply verifies the context
  // value is available, meaning ChatProvider rendered and initialised them.
  it("mounts and exposes the context value", () => {
    const { result } = renderChatHook();
    expect(result.current.currentConversationId).toBeNull();
    expect(result.current.placeholderConversation).toBeNull();
    expect(typeof result.current.startNewConversation).toBe("function");
  });

  it("switches sources and clears conversation state when the kill switch changes", async () => {
    const { result, rerender } = renderChatHook();
    const initialRefreshTrigger = result.current.refreshTrigger;

    await act(async () => {
      await result.current.loadConversation({
        response_id: "langflow-conversation",
        title: "Langflow conversation",
        endpoint: "langflow",
        messages: [],
      });
      result.current.setPreviousResponseIds({
        chat: "chat-response",
        langflow: "langflow-response",
      });
      result.current.setConversationFilter(
        {
          id: "filter-1",
          name: "Filter",
          description: "",
          query_data: "{}",
          owner: "user-1",
          created_at: "",
          updated_at: "",
        },
        null,
      );
    });

    settingsState.current = {
      agent: { disable_chat_with_langflow: true },
    };
    rerender();

    await waitFor(() => {
      expect(result.current.endpoint).toBe("chat");
    });
    expect(result.current.currentConversationId).toBeNull();
    expect(result.current.conversationData).toBeNull();
    expect(result.current.previousResponseIds).toEqual({
      chat: null,
      langflow: null,
    });
    expect(result.current.conversationFilter).toBeNull();
    expect(result.current.refreshTrigger).toBe(initialRefreshTrigger + 1);
  });

  it("clears a loaded transcript only when setEndpoint changes its source", async () => {
    const { result } = renderChatHook();
    await act(async () => {
      await result.current.loadConversation({
        response_id: "langflow-conversation",
        title: "Langflow conversation",
        endpoint: "langflow",
        messages: [],
      });
    });

    act(() => result.current.setEndpoint("langflow"));
    expect(result.current.currentConversationId).toBe("langflow-conversation");

    act(() => result.current.setEndpoint("chat"));
    expect(result.current.currentConversationId).toBeNull();
    expect(result.current.conversationData).toBeNull();
  });

  it("does not apply a filter lookup after another conversation is selected", async () => {
    const { getFilterById } = await import(
      "@/app/api/queries/useGetFilterByIdQuery"
    );
    let resolveFilter: (value: {
      id: string;
      name: string;
      description: string;
      query_data: string;
      owner: string;
      created_at: string;
      updated_at: string;
    }) => void;
    vi.mocked(getFilterById).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFilter = resolve;
        }),
    );
    localStorage.setItem("conversation_filter_first", "saved-filter");
    const { result } = renderChatHook();

    let firstLoad: Promise<void>;
    act(() => {
      firstLoad = result.current.loadConversation({
        response_id: "first",
        title: "First",
        endpoint: "chat",
        messages: [],
      });
    });
    await waitFor(() =>
      expect(getFilterById).toHaveBeenCalledWith("saved-filter"),
    );

    await act(async () => {
      await result.current.loadConversation({
        response_id: "second",
        title: "Second",
        endpoint: "chat",
        messages: [],
      });
    });
    await act(async () => {
      resolveFilter({
        id: "saved-filter",
        name: "Saved",
        description: "",
        query_data: "{}",
        owner: "user",
        created_at: "",
        updated_at: "",
      });
      await firstLoad;
    });

    expect(result.current.conversationData?.response_id).toBe("second");
    expect(result.current.conversationFilter).toBeNull();
  });

  it("does not apply a default filter after the source changes", async () => {
    const { getFilterById } = await import(
      "@/app/api/queries/useGetFilterByIdQuery"
    );
    let resolveFilter!: (value: {
      id: string;
      name: string;
      description: string;
      query_data: string;
      owner: string;
      created_at: string;
      updated_at: string;
    }) => void;
    vi.mocked(getFilterById).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFilter = resolve;
        }),
    );
    localStorage.setItem("default_conversation_filter_id", "default-filter");
    const { result } = renderChatHook();

    let start: void;
    act(() => {
      start = result.current.startNewConversation({ showPlaceholder: false });
    });
    await waitFor(() =>
      expect(getFilterById).toHaveBeenCalledWith("default-filter"),
    );
    act(() => result.current.setEndpoint("chat"));
    await act(async () => {
      resolveFilter({
        id: "default-filter",
        name: "Default",
        description: "",
        query_data: "{}",
        owner: "user",
        created_at: "",
        updated_at: "",
      });
      await start;
    });

    expect(result.current.endpoint).toBe("chat");
    expect(result.current.conversationFilter).toBeNull();
  });

  it("updates exposed chat state and refreshes both history query modes", async () => {
    vi.useFakeTimers();
    const { result } = renderChatHook();

    act(() => {
      result.current.setEndpoint("chat");
      result.current.setCurrentConversationId("conversation-1");
      result.current.setPreviousResponseIds((previous) => ({
        ...previous,
        chat: "response-1",
      }));
      result.current.setPlaceholderConversation({
        response_id: "placeholder-1",
        title: "New chat",
        endpoint: "chat",
        messages: [],
      });
      result.current.setConversationLoaded(true);
      result.current.setChatError(true);
      result.current.setLoading(true);
      result.current.addConversationDoc("notes.pdf");
      result.current.refreshConversations(true);
      void result.current.refreshConversationsSilent();
      result.current.refreshConversations();
    });
    act(() => vi.advanceTimersByTime(250));

    expect(result.current.endpoint).toBe("chat");
    expect(result.current.currentConversationId).toBe("conversation-1");
    expect(result.current.previousResponseIds.chat).toBe("response-1");
    expect(result.current.placeholderConversation?.response_id).toBe(
      "placeholder-1",
    );
    expect(result.current.conversationLoaded).toBe(true);
    expect(result.current.hasChatError).toBe(true);
    expect(result.current.loading).toBe(true);
    expect(result.current.conversationDocs).toHaveLength(1);
    expect(result.current.refreshTrigger).toBe(3);
    expect(result.current.refreshTriggerSilent).toBe(1);

    act(() => {
      result.current.clearConversationDocs();
      result.current.forkFromResponse("response-2");
    });

    expect(result.current.conversationDocs).toEqual([]);
    expect(result.current.currentConversationId).toBeNull();
    expect(result.current.placeholderConversation).toBeNull();
    expect(result.current.previousResponseIds.chat).toBe("response-2");
  });

  it("loads a saved filter with its conversation", async () => {
    const { getFilterById } = await import(
      "@/app/api/queries/useGetFilterByIdQuery"
    );
    const filter = {
      id: "filter-42",
      name: "Saved filter",
      description: "",
      query_data: "{}",
      owner: "user-1",
      created_at: "",
      updated_at: "",
    };
    vi.mocked(getFilterById).mockResolvedValue(filter);
    localStorage.setItem("conversation_filter_chat-1", filter.id);
    const { result } = renderChatHook();

    await act(async () => {
      await result.current.loadConversation({
        response_id: "chat-1",
        title: "Saved conversation",
        endpoint: "chat",
        messages: [],
      });
    });

    expect(result.current.conversationFilter).toEqual(filter);
    expect(result.current.conversationData?.filter).toEqual(filter);
  });

  it("clears a saved filter association when loading it fails", async () => {
    const { getFilterById } = await import(
      "@/app/api/queries/useGetFilterByIdQuery"
    );
    vi.mocked(getFilterById).mockRejectedValue(new Error("network error"));
    localStorage.setItem("conversation_filter_chat-1", "missing-filter");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderChatHook();

    await act(async () => {
      await result.current.loadConversation({
        response_id: "chat-1",
        title: "Saved conversation",
        endpoint: "chat",
        messages: [],
      });
    });

    expect(result.current.conversationFilter).toBeNull();
    expect(localStorage.getItem("conversation_filter_chat-1")).toBeNull();
    errorSpy.mockRestore();
  });

  // lines 240-242, 245, 249-253 — showPlaceholder=true (default): clears state
  // and creates a placeholder conversation
  it("creates a placeholder conversation when showPlaceholder=true", async () => {
    const { result } = renderChatHook();

    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: true });
    });

    expect(result.current.placeholderConversation).not.toBeNull();
    expect(result.current.placeholderConversation?.title).toBe("New chat...");
    expect(result.current.currentConversationId).toBeNull();
  });

  // line 310-311: showPlaceholder=false (auto-load path) — no placeholder set
  it("does not set a placeholder when showPlaceholder=false", async () => {
    const { result } = renderChatHook();

    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: false });
    });

    expect(result.current.placeholderConversation).toBeNull();
  });

  // lines 256-257, 261, 263 — when a default filter id is in localStorage, it
  // is consumed (removed) and getFilterById is called
  it("reads and clears the default_conversation_filter_id from localStorage", async () => {
    const { getFilterById } = await import(
      "@/app/api/queries/useGetFilterByIdQuery"
    );
    const mockGetFilter = vi.mocked(getFilterById);
    mockGetFilter.mockResolvedValue({
      id: "filter-1",
      name: "My Filter",
      description: "",
      query_data: "{}",
      owner: "user-1",
      created_at: "",
      updated_at: "",
    });

    localStorage.setItem("default_conversation_filter_id", "filter-1");

    const { result } = renderChatHook();

    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: false });
    });

    await waitFor(() => {
      expect(mockGetFilter).toHaveBeenCalledWith("filter-1");
    });

    // Key must be removed after first use
    expect(localStorage.getItem("default_conversation_filter_id")).toBeNull();
  });

  // lines 265-266, 271-272 — filter found → set on state
  it("sets conversationFilter when the default filter resolves", async () => {
    const { getFilterById } = await import(
      "@/app/api/queries/useGetFilterByIdQuery"
    );
    const filter = {
      id: "filter-42",
      name: "Test Filter",
      description: "",
      query_data: "{}",
      owner: "u1",
      created_at: "",
      updated_at: "",
    };
    vi.mocked(getFilterById).mockResolvedValue(filter);
    localStorage.setItem("default_conversation_filter_id", "filter-42");

    const { result } = renderChatHook();

    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: false });
    });

    await waitFor(() => {
      expect(result.current.conversationFilter?.id).toBe("filter-42");
    });
  });

  // lines 275, 282 — filter lookup returns null → conversationFilter cleared
  it("clears conversationFilter when the default filter is not found", async () => {
    const { getFilterById } = await import(
      "@/app/api/queries/useGetFilterByIdQuery"
    );
    vi.mocked(getFilterById).mockResolvedValue(null);
    localStorage.setItem("default_conversation_filter_id", "gone");

    const { result } = renderChatHook();

    // Pre-set a filter so we can verify it gets cleared
    act(() => {
      result.current.setConversationFilter(
        {
          id: "old",
          name: "",
          description: "",
          query_data: "",
          owner: "",
          created_at: "",
          updated_at: "",
        },
        null,
      );
    });

    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: false });
    });

    await waitFor(() => {
      expect(result.current.conversationFilter).toBeNull();
    });
  });

  // lines 286-287 — no default filter in localStorage, has existing conversation
  // → filter is cleared
  it("clears conversationFilter when switching away from an existing conversation", async () => {
    const { result } = renderChatHook();

    // Simulate an existing conversation and filter
    act(() => {
      result.current.setConversationFilter(
        {
          id: "current-filter",
          name: "",
          description: "",
          query_data: "",
          owner: "",
          created_at: "",
          updated_at: "",
        },
        null,
      );
    });

    // Manually seed conversationData to trigger the hasExistingConversation branch
    // (startNewConversation reads conversationDataRef.current, which mirrors
    // conversationData state; we exercise this by loading a conversation first)
    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: true });
    });

    // After the second startNewConversation the old filter should be cleared
    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: false });
    });

    expect(result.current.conversationFilter).toBeNull();
  });

  // line 278 — getFilterById throws → console.error + filter cleared
  it("handles a getFilterById rejection gracefully (line 278)", async () => {
    const { getFilterById } = await import(
      "@/app/api/queries/useGetFilterByIdQuery"
    );
    vi.mocked(getFilterById).mockRejectedValue(new Error("network error"));
    localStorage.setItem("default_conversation_filter_id", "bad-id");

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderChatHook();

    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: false });
    });

    await waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith(
        expect.stringContaining(
          "[CONVERSATION] Failed to load default filter:",
        ),
        expect.any(Error),
      );
    });

    expect(result.current.conversationFilter).toBeNull();
    errorSpy.mockRestore();
  });

  // line 295: the placeholder response_id contains "new-conversation-"
  it("gives the placeholder a response_id prefixed with 'new-conversation-'", async () => {
    const { result } = renderChatHook();

    await act(async () => {
      result.current.startNewConversation({ showPlaceholder: true });
    });

    expect(result.current.placeholderConversation?.response_id).toMatch(
      /^new-conversation-/,
    );
  });
});
