import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useImeComposition } from "./use-ime-composition";

const plainEnter = { isComposing: false, keyCode: 13 };

function enterEvent(nativeEvent = plainEnter) {
  return {
    key: "Enter",
    shiftKey: false,
    preventDefault: vi.fn(),
    nativeEvent,
  };
}

describe("useImeComposition", () => {
  it("blocks the Enter Safari fires just after composition ends, then allows a later Enter", () => {
    let now = 1_000;
    const nowSpy = vi.spyOn(performance, "now").mockImplementation(() => now);
    const { result } = renderHook(() => useImeComposition());

    result.current.inputProps.onCompositionStart();
    expect(result.current.readState().composing).toBe(true);
    expect(result.current.blockEnter(enterEvent())).toBe(true);

    now = 1_020;
    result.current.inputProps.onCompositionEnd();
    const leftover = enterEvent();
    expect(result.current.blockEnter(leftover)).toBe(true);
    expect(leftover.preventDefault).toHaveBeenCalledOnce();

    now = 1_080;
    const send = enterEvent();
    expect(result.current.blockEnter(send)).toBe(false);
    expect(send.preventDefault).not.toHaveBeenCalled();

    nowSpy.mockRestore();
  });

  it("clears a finished composition on blur so the next Enter sends", () => {
    const { result } = renderHook(() => useImeComposition());

    result.current.inputProps.onCompositionEnd();
    result.current.inputProps.onBlur();

    expect(result.current.readState()).toEqual({
      composing: false,
      compositionEndedAt: 0,
      now: 0,
    });
    expect(result.current.blockEnter(enterEvent())).toBe(false);
  });

  it("submits on Enter through the props a future field spreads on", () => {
    const onSubmit = vi.fn();
    const { result, rerender } = renderHook(
      ({ submit }) => useImeComposition(submit),
      { initialProps: { submit: onSubmit } },
    );

    const send = enterEvent();
    result.current.inputProps.onKeyDown(send);
    expect(send.preventDefault).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledOnce();

    const nextSubmit = vi.fn();
    rerender({ submit: nextSubmit });
    result.current.inputProps.onCompositionStart();
    result.current.handleKeyDown(enterEvent());
    expect(nextSubmit).not.toHaveBeenCalled();
  });

  it("treats Space during composition as a candidate key and a later Space as a real space", () => {
    const { result } = renderHook(() => useImeComposition());

    result.current.inputProps.onCompositionStart();
    expect(
      result.current.isImeCandidateKey({ isComposing: true, keyCode: 32 }),
    ).toBe(true);

    result.current.inputProps.onCompositionEnd();
    expect(result.current.isImeCandidateKey(plainEnter)).toBe(false);
  });
});
