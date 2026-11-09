import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useNarrowLayout } from "./use-narrow-layout";

describe("useNarrowLayout", () => {
  it("returns true when viewport matches narrow query and false otherwise", () => {
    let changeHandler: (() => void) | null = null;
    let matchesValue = false;

    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: matchesValue,
        media: query,
        addEventListener: vi.fn((event: string, handler: () => void) => {
          if (event === "change") changeHandler = handler;
        }),
        removeEventListener: vi.fn(),
      })),
    );

    const { result, rerender } = renderHook(() => useNarrowLayout());
    expect(result.current).toBe(false);

    matchesValue = true;
    act(() => {
      if (changeHandler) {
        (changeHandler as () => void)();
      }
    });
    rerender();
    expect(result.current).toBe(true);

    vi.unstubAllGlobals();
  });
});
