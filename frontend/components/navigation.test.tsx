import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { KnowledgeFilterProvider } from "@/contexts/knowledge-filter-context";
import { renderWithProviders } from "@/test-utils/render";
import { Navigation } from "./navigation";

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/contexts/brand-context", () => ({
  useIsCloudBrand: () => false,
}));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({ isNoAuthMode: false }),
}));

vi.mock("@/contexts/chat-context", () => ({
  useChat: () => ({
    currentConversationId: "conv-1",
    loadConversation: vi.fn(),
    startNewConversation: vi.fn(),
    deleteConversation: vi.fn(),
    renameConversation: vi.fn(),
    loading: false,
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
  useGetFiltersQuery: () => ({
    data: [],
    isLoading: false,
  }),
}));

describe("Navigation", () => {
  it("triggers onNavigate when route link or conversation item is clicked", async () => {
    const user = userEvent.setup();
    const handleNavigate = vi.fn();

    const conversations = [
      {
        response_id: "conv-1",
        title: "Test Conversation",
        timestamp: "2025-01-01T00:00:00Z",
      },
    ];

    renderWithProviders(
      <KnowledgeFilterProvider>
        <Navigation
          conversations={conversations as any}
          isConversationsLoading={false}
          onNavigate={handleNavigate}
        />
      </KnowledgeFilterProvider>,
    );

    // Test conversation item click triggers onNavigate
    const conversationItem = screen.getByText("Test Conversation");
    await user.click(conversationItem);
    expect(handleNavigate).toHaveBeenCalled();
  });
});
