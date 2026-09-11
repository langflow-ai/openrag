/**
 * Tests for the Header component.
 *
 * The Header reads from several contexts and react-query hooks. We vi.mock
 * each hook dependency so the unit tests remain fast and isolated — the
 * contexts themselves are tested elsewhere.
 *
 * Covered lines (per diff gate):
 *   22, 24 — activeTaskCount derivation
 *   28-29  — failedTaskCount derivation + badge render
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Header } from "@/components/header";

// ─── mock all context/hook dependencies ───────────────────────────────────────

vi.mock("@/contexts/auth-context", () => ({
  useAuth: vi.fn(),
}));

vi.mock("@/contexts/brand-context", () => ({
  useIsCloudBrand: vi.fn(),
}));

vi.mock("@/contexts/task-context", () => ({
  useTask: vi.fn(),
}));

vi.mock("@/contexts/console-status-context", () => ({
  useConsoleStatus: vi.fn(),
  useToggleTaskMenu: vi.fn(),
}));

vi.mock("@/components/provider-health-banner", () => ({
  useProviderHealth: vi.fn(),
}));

// Heavy child components: keep them as lightweight stubs so the test only
// asserts on Header's own output.
vi.mock("@/components/user-nav", () => ({
  UserNav: () => <div data-testid="user-nav" />,
}));

vi.mock("@/components/console-status", () => ({
  ConsoleStatusButton: () => <button data-testid="console-status-btn" />,
}));

vi.mock("@/components/brand-switcher", () => ({
  BrandSwitcher: () => <div data-testid="brand-switcher" />,
}));

vi.mock("@/components/dev-role-toggle", () => ({
  DevRoleToggle: () => <div data-testid="dev-role-toggle" />,
}));

vi.mock("@/components/icons/openrag-logo", () => ({
  default: () => <svg data-testid="openrag-logo" />,
}));

// ─── import mocks after vi.mock declarations ──────────────────────────────────

import { useProviderHealth } from "@/components/provider-health-banner";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  useConsoleStatus,
  useToggleTaskMenu,
} from "@/contexts/console-status-context";
import { useTask } from "@/contexts/task-context";

// ─── helpers ──────────────────────────────────────────────────────────────────

const noop = () => {};

function setupMocks(tasks: Array<{ status: string }>, runMode = "oss") {
  vi.mocked(useAuth).mockReturnValue({ runMode } as ReturnType<typeof useAuth>);
  vi.mocked(useIsCloudBrand).mockReturnValue(false);
  vi.mocked(useTask).mockReturnValue({ tasks } as ReturnType<typeof useTask>);
  vi.mocked(useToggleTaskMenu).mockReturnValue(noop);
  vi.mocked(useConsoleStatus).mockReturnValue({
    toggle: noop,
    isOpen: false,
    overallStatus: "healthy",
  } as ReturnType<typeof useConsoleStatus>);
  vi.mocked(useProviderHealth).mockReturnValue({
    isUnhealthy: false,
  } as ReturnType<typeof useProviderHealth>);
}

// ─── tests ────────────────────────────────────────────────────────────────────

describe("Header", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with no tasks — no badge visible", () => {
    setupMocks([]);
    render(<Header />);
    // Neither active nor failed badge should appear.
    expect(screen.queryByText(/\d/)).toBeNull();
  });

  it("shows an active-task badge for pending / running / processing tasks (line 22-24)", () => {
    setupMocks([
      { status: "pending" },
      { status: "running" },
      { status: "processing" },
    ]);
    render(<Header />);
    // Badge text = "3"
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows a failed-task badge when there are failed/error tasks and no active tasks (lines 28-29)", () => {
    setupMocks([{ status: "failed" }, { status: "error" }]);
    render(<Header />);
    // Badge text = "2"
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("shows only the active badge when both active and failed tasks exist", () => {
    setupMocks([{ status: "running" }, { status: "failed" }]);
    render(<Header />);
    // Only 1 active task badge — failed badge is suppressed.
    expect(screen.getByText("1")).toBeInTheDocument();
    // There should be exactly one badge (the active one).
    const badges = screen.getAllByText(/^\d+$/);
    expect(badges).toHaveLength(1);
  });

  it("caps active badge at '99+' when count exceeds 99", () => {
    const manyTasks = Array.from({ length: 100 }, () => ({
      status: "running",
    }));
    setupMocks(manyTasks);
    render(<Header />);
    expect(screen.getByText("99+")).toBeInTheDocument();
  });

  it("fires toggleTaskMenu when the bell button is clicked", async () => {
    const toggleFn = vi.fn();
    setupMocks([]);
    vi.mocked(useToggleTaskMenu).mockReturnValue(toggleFn);
    render(<Header />);
    await userEvent.click(screen.getByTestId("task-menu-toggle"));
    expect(toggleFn).toHaveBeenCalledOnce();
  });
});
