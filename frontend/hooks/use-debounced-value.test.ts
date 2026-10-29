import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedValue } from "./use-debounced-value";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the initial value immediately", () => {
    const { result } = renderHook(() => useDebouncedValue("a", 100));
    expect(result.current).toBe("a");
  });

  it("applies a change only after the delay has elapsed", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 100),
      { initialProps: { value: "a" } },
    );

    rerender({ value: "b" });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(99);
    });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe("b");
  });

  it("restarts the wait on every change so a burst applies only the last value", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 100),
      { initialProps: { value: "a" } },
    );

    for (const value of ["b", "c", "d"]) {
      rerender({ value });
      act(() => {
        vi.advanceTimersByTime(60);
      });
    }
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(result.current).toBe("d");
  });

  it("applies the value on the next tick when the delay is 0", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 0),
      { initialProps: { value: "a" } },
    );

    rerender({ value: "b" });
    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(result.current).toBe("b");
  });

  it("does not update after unmount", () => {
    const { result, rerender, unmount } = renderHook(
      ({ value }) => useDebouncedValue(value, 100),
      { initialProps: { value: "a" } },
    );

    rerender({ value: "b" });
    unmount();

    expect(() => {
      act(() => {
        vi.advanceTimersByTime(200);
      });
    }).not.toThrow();
    expect(result.current).toBe("a");
  });
});
