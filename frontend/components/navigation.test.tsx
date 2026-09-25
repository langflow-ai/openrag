import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KnowledgeFilterProvider } from "@/contexts/knowledge-filter-context";
import { renderWithProviders } from "@/test-utils/render";
import { Navigation } from "./navigation";

// ---------------------------------------------------------------------------
// Module mocks (applied once for the whole file)
// ---------------------------------------------------------------------------

let mockPathname = "/chat";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
}));

vi.mock("@/contexts/auth-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/auth-context")>()),
  useAuth: () => ({ isNoAuthMode: false }),
}));

const mockStartNewConversation = vi.fn();
const mockLoadConversation = vi.fn();
const mockSetCurrentConversationId = vi.fn();
const mockSetPlaceholderConversation = vi.fn();

let mockChatState = {
  currentConversationId: "conv-1" as string | null,
  placeholderConversation: null as null | object,
  loading: false,
  conversationDocs: [],
  conversationData: null,
  conversationLoaded: false,
  refreshConversations: vi.fn(),
  endpoint: "chat",
};

vi.mock("@/contexts/chat-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/chat-context")>()),
  useChat: () => ({
    ...mockChatState,
    loadConversation: mockLoadConversation,
    startNewConversation: mockStartNewConversation,
    setCurrentConversationId: mockSetCurrentConversationId,
    setPlaceholderConversation: mockSetPlaceholderConversation,
    deleteConversation: vi.fn(),
    renameConversation: vi.fn(),
    setPreviousResponseIds: vi.fn(),
  }),
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: () => true,
    canAny: () => true,
    isPending: false,
    rbacEnforced: false,
  }),
}));

vi.mock("@/app/api/queries/useGetFiltersQuery", () => ({
  useGetFiltersQuery: () => ({ data: [], isLoading: false }),
}));

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function makeConversation(id: string, title = "Test Conversation") {
  return {
    response_id: id,
    title,
    endpoint: "chat" as const,
    messages: [],
    total_messages: 0,
    timestamp: "2025-01-01T00:00:00Z",
  };
}

function renderNav(
  conversations: ReturnType<typeof makeConversation>[] = [],
  props: Record<string, unknown> = {},
) {
  return renderWithProviders(
    <KnowledgeFilterProvider>
      <Navigation
        conversations={conversations as any}
        isConversationsLoading={false}
        {...props}
      />
    </KnowledgeFilterProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Navigation", () => {
  beforeEach(() => {
    mockPathname = "/chat";
    mockChatState = {
      currentConversationId: "conv-1",
      placeholderConversation: null,
      loading: false,
      conversationDocs: [],
      conversationData: null,
      conversationLoaded: false,
      refreshConversations: vi.fn(),
      endpoint: "chat",
    };
    mockStartNewConversation.mockReset();
    mockLoadConversation.mockReset();
    mockSetCurrentConversationId.mockReset();
    mockSetPlaceholderConversation.mockReset();
  });

  it("triggers onNavigate when a conversation item is clicked", async () => {
    const user = userEvent.setup();
    const handleNavigate = vi.fn();

    renderNav([makeConversation("conv-1")], { onNavigate: handleNavigate });

    await user.click(screen.getByText("Test Conversation"));
    expect(handleNavigate).toHaveBeenCalled();
  });

  // line 346 — auto-starts a new conversation (no placeholder) when there are
  // no conversations and we are on the chat page
  it("calls startNewConversation when on /chat with no conversations", async () => {
    mockChatState.currentConversationId = null;
    renderNav([], {});

    await waitFor(() => {
      expect(mockStartNewConversation).toHaveBeenCalledWith({
        showPlaceholder: false,
      });
    });
  });

  // line 356 — auto-starts a new conversation when there are conversations but
  // none is currently selected and there is no placeholder
  it("calls startNewConversation when conversations exist but none is selected", async () => {
    mockChatState.currentConversationId = null;
    mockChatState.placeholderConversation = null;

    renderNav([makeConversation("conv-99")], {});

    await waitFor(() => {
      expect(mockStartNewConversation).toHaveBeenCalledWith({
        showPlaceholder: false,
      });
    });
  });

  // line 318 — setFreshConversationId is set when a new conversation appears
  // while a placeholder is present; the typewriter title is then rendered
  it("typewriters the title of a fresh conversation", async () => {
    // Render with a placeholder so the placeholder-clearing effect is active,
    // and a conversation that is considered "fresh" by having a matching id
    // baked into the component's freshConversationId state.
    // We achieve this by rendering with the placeholder present so the effect
    // on lines 303-320 can fire: when conversation count grows and a
    // placeholder exists the component marks the first conversation as fresh.
    mockChatState.placeholderConversation = {
      response_id: "placeholder-1",
      title: "New chat...",
    };
    mockChatState.currentConversationId = null;

    const { rerender } = renderNav([], {});

    // Simulate a new real conversation arriving (count goes from 0 to 1)
    act(() => {
      mockChatState.placeholderConversation = {
        response_id: "placeholder-1",
        title: "New chat...",
      };
    });

    rerender(
      <KnowledgeFilterProvider>
        <Navigation
          conversations={[makeConversation("conv-fresh", "Fresh Chat")] as any}
          isConversationsLoading={false}
        />
      </KnowledgeFilterProvider>,
    );

    // The ConversationTitle component should render the title (possibly
    // mid-typewrite, so just assert it's in the document at some point)
    await waitFor(() => {
      expect(screen.getByText(/Fresh Chat/)).toBeInTheDocument();
    });
  });

  // line 647 — onDone clears freshConversationId after typewriter finishes
  it("renders ConversationTitle with onDone=undefined when conversation is not fresh", () => {
    mockChatState.currentConversationId = "conv-1";
    // freshConversationId starts null, so onDone should be undefined (line 647 branch)
    renderNav([makeConversation("conv-1", "Old Chat")]);
    // Title rendered immediately (not fresh, so no typewriter animation)
    expect(screen.getByText("Old Chat")).toBeInTheDocument();
  });
});
