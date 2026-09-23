import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTypewriter } from "./use-typewriter";

describe("useTypewriter", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the full text immediately when inactive", () => {
    const { result } = renderHook(() => useTypewriter("Hello world", false));
    expect(result.current).toBe("Hello world");
  });

  it("starts with an empty string when active", () => {
    const { result } = renderHook(() => useTypewriter("Hi", true));
    expect(result.current).toBe("");
  });

  it("reveals characters one by one at the given speed", () => {
    const speed = 28;
    const { result } = renderHook(() =>
      useTypewriter("abc", true, undefined, speed),
    );

    expect(result.current).toBe("");

    act(() => {
      vi.advanceTimersByTime(speed);
    });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(speed);
    });
    expect(result.current).toBe("ab");

    act(() => {
      vi.advanceTimersByTime(speed);
    });
    expect(result.current).toBe("abc");
  });

  it("calls onDone once when the animation completes", () => {
    const onDone = vi.fn();
    const speed = 10;
    renderHook(() => useTypewriter("xy", true, onDone, speed));

    act(() => {
      vi.advanceTimersByTime(speed);
    }); // 'x'
    expect(onDone).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(speed);
    }); // 'xy' — last char
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("shows the full text immediately when switching active → inactive", () => {
    let active = true;
    const { result, rerender } = renderHook(() =>
      useTypewriter("Hello", active, undefined, 10),
    );
    expect(result.current).toBe("");

    // flip to inactive before the animation finishes
    active = false;
    rerender();

    expect(result.current).toBe("Hello");
  });

  it("resets and restarts when text changes while active — clears pending timer (lines 22-23)", () => {
    let text = "AB";
    const { result, rerender } = renderHook(() =>
      useTypewriter(text, true, undefined, 50),
    );

    // First tick scheduled but NOT yet fired — frameRef.current is set.
    // Change text now so the next effect invocation hits the clearTimeout guard.
    text = "XY";
    act(() => {
      rerender(); // triggers new effect; lines 22-23 fire to cancel old timer
    });

    // Should have reset to "" immediately
    expect(result.current).toBe("");

    act(() => {
      vi.advanceTimersByTime(50);
    }); // 'X' from new text
    expect(result.current).toBe("X");
  });

  it("clears any pending timer on unmount", () => {
    const { unmount } = renderHook(() =>
      useTypewriter("test", true, undefined, 100),
    );
    // Unmounting before timers fire should not throw
    expect(() => unmount()).not.toThrow();
    act(() => {
      vi.runAllTimers();
    });
  });
});
