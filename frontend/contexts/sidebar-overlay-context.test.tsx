import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  SidebarOverlayProvider,
  useSidebarOverlay,
} from "./sidebar-overlay-context";

describe("SidebarOverlayContext", () => {
  it("provides fallback default callbacks when used outside provider", () => {
    const { result } = renderHook(() => useSidebarOverlay());
    expect(result.current.isVisible).toBe(false);
    expect(result.current.isPinned).toBe(false);
    expect(result.current.isCollapsed).toBe(false);
    // Call fallback functions to ensure coverage
    result.current.show();
    result.current.hide();
    result.current.hideNow();
    result.current.pin();
    result.current.unpin();
    result.current.expand();
    result.current.collapse();
  });

  it("manages visibility, pinned, and collapsed states correctly", () => {
    vi.useFakeTimers();

    const wrapper = ({ children }: { children: ReactNode }) => (
      <SidebarOverlayProvider>{children}</SidebarOverlayProvider>
    );

    const { result } = renderHook(() => useSidebarOverlay(), { wrapper });

    expect(result.current.isVisible).toBe(false);
    expect(result.current.isPinned).toBe(false);
    expect(result.current.isCollapsed).toBe(false);

    // show
    act(() => {
      result.current.show();
    });
    expect(result.current.isVisible).toBe(true);

    // hide with timeout
    act(() => {
      result.current.hide();
    });
    expect(result.current.isVisible).toBe(true);
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(result.current.isVisible).toBe(false);

    // hideNow
    act(() => {
      result.current.show();
    });
    expect(result.current.isVisible).toBe(true);
    act(() => {
      result.current.hideNow();
    });
    expect(result.current.isVisible).toBe(false);

    // pin & unpin
    act(() => {
      result.current.pin();
    });
    expect(result.current.isPinned).toBe(true);
    expect(result.current.isVisible).toBe(true);

    // hide while pinned should do nothing
    act(() => {
      result.current.hide();
    });
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(result.current.isVisible).toBe(true);

    // unpin
    act(() => {
      result.current.unpin();
    });
    expect(result.current.isPinned).toBe(false);
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(result.current.isVisible).toBe(false);

    // collapse & expand
    act(() => {
      result.current.collapse();
    });
    expect(result.current.isCollapsed).toBe(true);

    act(() => {
      result.current.expand();
    });
    expect(result.current.isCollapsed).toBe(false);

    vi.useRealTimers();
  });
});
