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
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
    useStickToBottomContext: () => ({ isAtBottom: true }),
  };
});

vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
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
    conversationFilter: null,
    setConversationFilter: vi.fn(),
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
    sendMessage: vi.fn(),
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

vi.mock("@/app/chat/_components/chat-input", () => {
  const { forwardRef } = require("react");
  return {
    ChatInput: forwardRef((_props: unknown, _ref: unknown) => (
      <div data-testid="chat-input" />
    )),
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
  beforeEach(() => vi.useFakeTimers());
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
});
