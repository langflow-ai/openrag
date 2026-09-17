import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Header } from "./header";

const {
  mockToggleTaskMenu,
  mockToggleConsole,
  mockShowSidebar,
  mockHideSidebar,
  mockPinSidebar,
  mockUnpinSidebar,
  mockExpandSidebar,
} = vi.hoisted(() => ({
  mockToggleTaskMenu: vi.fn(),
  mockToggleConsole: vi.fn(),
  mockShowSidebar: vi.fn(),
  mockHideSidebar: vi.fn(),
  mockPinSidebar: vi.fn(),
  mockUnpinSidebar: vi.fn(),
  mockExpandSidebar: vi.fn(),
}));

// Mutable tasks list so individual tests can swap in different data.
const mockTasksHolder = vi.hoisted(() => ({
  tasks: [] as { status: string }[],
}));

vi.mock("@/contexts/brand-context", () => ({
  useIsCloudBrand: () => false,
}));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({ runMode: "oss" }),
}));

vi.mock("@/contexts/task-context", () => ({
  useTask: () => ({ tasks: mockTasksHolder.tasks }),
}));

vi.mock("@/contexts/console-status-context", () => ({
  useToggleTaskMenu: () => mockToggleTaskMenu,
  useConsoleStatus: () => ({
    hasProblem: false,
    toggle: mockToggleConsole,
    isOpen: false,
    overallStatus: "healthy",
  }),
}));

vi.mock("./provider-health-banner", () => ({
  useProviderHealth: () => ({ isUnhealthy: false }),
}));

vi.mock("@/components/user-nav", () => ({
  UserNav: () => <div data-testid="user-nav" />,
}));

vi.mock("@/hooks/use-narrow-layout", () => ({
  useNarrowLayout: vi.fn().mockReturnValue(false),
}));

vi.mock("@/contexts/sidebar-overlay-context", () => ({
  useSidebarOverlay: vi.fn().mockReturnValue({
    show: mockShowSidebar,
    hide: mockHideSidebar,
    isPinned: false,
    isCollapsed: false,
    pin: mockPinSidebar,
    unpin: mockUnpinSidebar,
    expand: mockExpandSidebar,
  }),
}));

import { useSidebarOverlay } from "@/contexts/sidebar-overlay-context";
import { useNarrowLayout } from "@/hooks/use-narrow-layout";

describe("Header", () => {
  it("renders brand and header elements in wide non-collapsed layout", () => {
    mockTasksHolder.tasks = [];
    render(<Header />);
    expect(screen.getByText("OpenRAG")).toBeInTheDocument();
    expect(screen.queryByLabelText("Open navigation")).not.toBeInTheDocument();
  });

  it("renders expand button when collapsed in wide layout", async () => {
    const user = userEvent.setup();
    vi.mocked(useSidebarOverlay).mockReturnValue({
      show: mockShowSidebar,
      hide: mockHideSidebar,
      isPinned: false,
      isCollapsed: true,
      pin: mockPinSidebar,
      unpin: mockUnpinSidebar,
      expand: mockExpandSidebar,
      isVisible: false,
      hideNow: vi.fn(),
      collapse: vi.fn(),
    });

    render(<Header />);
    const openBtn = screen.getByLabelText("Open navigation");
    expect(openBtn).toBeInTheDocument();

    await user.hover(openBtn);
    expect(mockShowSidebar).toHaveBeenCalled();

    await user.click(openBtn);
    expect(mockExpandSidebar).toHaveBeenCalled();
  });

  it("renders open/close navigation toggle in narrow layout", async () => {
    const user = userEvent.setup();
    vi.mocked(useNarrowLayout).mockReturnValue(true);
    vi.mocked(useSidebarOverlay).mockReturnValue({
      show: mockShowSidebar,
      hide: mockHideSidebar,
      isPinned: false,
      isCollapsed: false,
      pin: mockPinSidebar,
      unpin: mockUnpinSidebar,
      expand: mockExpandSidebar,
      isVisible: false,
      hideNow: vi.fn(),
      collapse: vi.fn(),
    });

    render(<Header />);
    const navBtn = screen.getByLabelText("Open navigation");
    expect(navBtn).toBeInTheDocument();

    await user.click(navBtn);
    expect(mockPinSidebar).toHaveBeenCalled();
  });
});

describe("Header — notification badge counts", () => {
  it("shows active task count badge when pending/running/processing tasks exist", () => {
    mockTasksHolder.tasks = [
      { status: "pending" },
      { status: "running" },
      { status: "processing" },
    ];
    render(<Header />);
    // activeTaskCount = 3, badge should display "3"
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows failed task count badge when only failed/error tasks exist", () => {
    mockTasksHolder.tasks = [{ status: "failed" }, { status: "error" }];
    render(<Header />);
    // activeTaskCount = 0, failedTaskCount = 2 → red badge with "2"
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("shows active badge and not failed badge when both active and failed tasks exist", () => {
    mockTasksHolder.tasks = [{ status: "running" }, { status: "failed" }];
    render(<Header />);
    // activeTaskCount = 1 takes precedence; active badge shows, failed badge hidden
    expect(screen.getByText("1")).toBeInTheDocument();
    // Only one badge rendered
    expect(screen.getAllByText(/^\d+$/).length).toBe(1);
  });

  it("shows no badge when all tasks are in terminal non-failed states", () => {
    mockTasksHolder.tasks = [{ status: "completed" }, { status: "cancelled" }];
    render(<Header />);
    expect(screen.queryByText(/^\d+$/)).toBeNull();
  });
});
