import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test-utils/render";
import { ChatRenderer } from "./chat-renderer";

const {
  mockCollapseSidebar,
  mockExpandSidebar,
  mockHideNow,
  mockUnpinSidebar,
  mockShowSidebar,
  mockHideSidebar,
} = vi.hoisted(() => ({
  mockCollapseSidebar: vi.fn(),
  mockExpandSidebar: vi.fn(),
  mockHideNow: vi.fn(),
  mockUnpinSidebar: vi.fn(),
  mockShowSidebar: vi.fn(),
  mockHideSidebar: vi.fn(),
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/app/api/queries/useGetConversationsQuery", () => ({
  useGetConversationsQuery: () => ({
    data: [],
    isLoading: false,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/app/api/queries/useGetFilterByIdQuery", () => ({
  getFilterById: vi.fn(),
}));

vi.mock("@/app/api/mutations/useUpdateOnboardingStateMutation", () => ({
  useUpdateOnboardingStateMutation: () => ({
    mutate: vi.fn(),
  }),
}));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isNoAuthMode: false,
  }),
}));

vi.mock("@/contexts/brand-context", () => ({
  useIsCloudBrand: () => false,
}));

vi.mock("@/contexts/chat-context", () => ({
  useChat: () => ({
    endpoint: "http://localhost",
    refreshTrigger: 0,
    refreshTriggerSilent: 0,
    refreshConversations: 0,
    startNewConversation: vi.fn(),
    setConversationFilter: vi.fn(),
    setOnboardingComplete: vi.fn(),
    currentConversationId: null,
    conversations: [],
    isLoading: false,
  }),
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: () => true,
    isLoading: false,
    rbacEnforced: false,
  }),
}));

vi.mock("@/components/navigation", () => ({
  Navigation: () => <div data-testid="navigation" />,
}));

vi.mock("@/lib/analytics", () => ({
  page: vi.fn(),
}));

vi.mock("@/hooks/use-narrow-layout", () => ({
  useNarrowLayout: vi.fn().mockReturnValue(false),
}));

vi.mock("@/contexts/sidebar-overlay-context", () => ({
  useSidebarOverlay: vi.fn().mockReturnValue({
    isVisible: false,
    isPinned: false,
    isCollapsed: false,
    show: mockShowSidebar,
    hide: mockHideSidebar,
    hideNow: mockHideNow,
    pin: vi.fn(),
    unpin: mockUnpinSidebar,
    expand: mockExpandSidebar,
    collapse: mockCollapseSidebar,
  }),
}));

import { useSidebarOverlay } from "@/contexts/sidebar-overlay-context";
import { useNarrowLayout } from "@/hooks/use-narrow-layout";

describe("ChatRenderer", () => {
  const defaultSettings: any = {
    onboarding: {
      current_step: 4,
    },
  };

  it("renders wide layout and responds to separator resize drag & keyboard events", () => {
    // Stub ResizeObserver
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as any;

    const chromeDiv = document.createElement("div");
    chromeDiv.id = "app-top-chrome";
    Object.defineProperty(chromeDiv, "offsetHeight", {
      value: 60,
      configurable: true,
    });
    document.body.appendChild(chromeDiv);

    renderWithProviders(
      <ChatRenderer settings={defaultSettings}>
        <div data-testid="child-content">Content</div>
      </ChatRenderer>,
    );

    expect(screen.getByTestId("child-content")).toBeInTheDocument();
    expect(screen.getByTestId("navigation")).toBeInTheDocument();

    const separator = screen.getByRole("separator", { name: "Resize sidebar" });
    expect(separator).toBeInTheDocument();

    // Mouse drag
    fireEvent.mouseDown(separator, { clientX: 200 });
    expect(mockHideNow).toHaveBeenCalled();
    fireEvent.mouseMove(document, { clientX: 250 });
    expect(mockExpandSidebar).toHaveBeenCalled();
    fireEvent.mouseMove(document, { clientX: 20 });
    expect(mockCollapseSidebar).toHaveBeenCalled();
    fireEvent.mouseUp(document);

    // Keyboard resize
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(mockExpandSidebar).toHaveBeenCalled();
    fireEvent.keyDown(separator, { key: "ArrowLeft" });

    document.body.removeChild(chromeDiv);
  });

  it("renders collapsed overlay in wide layout when collapsed", () => {
    vi.mocked(useSidebarOverlay).mockReturnValue({
      isVisible: true,
      isPinned: false,
      isCollapsed: true,
      show: mockShowSidebar,
      hide: mockHideSidebar,
      hideNow: mockHideNow,
      pin: vi.fn(),
      unpin: mockUnpinSidebar,
      expand: mockExpandSidebar,
      collapse: mockCollapseSidebar,
    });

    renderWithProviders(
      <ChatRenderer settings={defaultSettings}>
        <div>Content</div>
      </ChatRenderer>,
    );

    const nav = screen.getByRole("navigation");
    fireEvent.mouseEnter(nav);
    expect(mockShowSidebar).toHaveBeenCalled();
    fireEvent.mouseLeave(nav);
    expect(mockHideSidebar).toHaveBeenCalled();
  });

  it("renders narrow layout with pinned overlay backdrop", async () => {
    const user = userEvent.setup();
    vi.mocked(useNarrowLayout).mockReturnValue(true);
    vi.mocked(useSidebarOverlay).mockReturnValue({
      isVisible: true,
      isPinned: true,
      isCollapsed: false,
      show: mockShowSidebar,
      hide: mockHideSidebar,
      hideNow: mockHideNow,
      pin: vi.fn(),
      unpin: mockUnpinSidebar,
      expand: mockExpandSidebar,
      collapse: mockCollapseSidebar,
    });

    renderWithProviders(
      <ChatRenderer settings={defaultSettings}>
        <div>Content</div>
      </ChatRenderer>,
    );

    const closeNavBtn = screen.getByLabelText("Close navigation");
    expect(closeNavBtn).toBeInTheDocument();
    await user.click(closeNavBtn);
    expect(mockUnpinSidebar).toHaveBeenCalled();
  });
});
