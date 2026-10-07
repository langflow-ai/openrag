import { describe, expect, it, vi } from "vitest";
import {
  blockImeEnter,
  handleInputKeyDown,
  IME_PROCESS_KEY_CODE,
  isImeCompositionEvent,
  SAFARI_IME_ENTER_WINDOW_MS,
  shouldCancelImeEnter,
} from "./ime-composition";

const plainEnter = { isComposing: false, keyCode: 13 };
const idle = { composing: false, compositionEndedAt: 0, now: 1_000 };

function enterEvent(
  nativeEvent: { isComposing: boolean; keyCode: number },
  shiftKey = false,
) {
  return {
    key: "Enter",
    shiftKey,
    preventDefault: vi.fn(),
    nativeEvent,
  };
}

describe("isImeCompositionEvent", () => {
  it("treats a normal Enter as a send", () => {
    expect(isImeCompositionEvent(plainEnter, idle)).toBe(false);
  });

  it("treats Enter during an open composition as IME confirmation", () => {
    expect(
      isImeCompositionEvent({ isComposing: true, keyCode: 13 }, idle),
    ).toBe(true);
    expect(
      isImeCompositionEvent(plainEnter, { ...idle, composing: true }),
    ).toBe(true);
  });

  it("treats the IME processing key as confirmation", () => {
    expect(
      isImeCompositionEvent(
        { isComposing: false, keyCode: IME_PROCESS_KEY_CODE },
        idle,
      ),
    ).toBe(true);
  });

  it("treats the Enter Safari fires just after compositionend as confirmation", () => {
    const endedAt = 1_000;
    expect(
      isImeCompositionEvent(plainEnter, {
        composing: false,
        compositionEndedAt: endedAt,
        now: endedAt + SAFARI_IME_ENTER_WINDOW_MS - 1,
      }),
    ).toBe(true);
  });

  it("lets a later Enter send", () => {
    const endedAt = 1_000;
    expect(
      isImeCompositionEvent(plainEnter, {
        composing: false,
        compositionEndedAt: endedAt,
        now: endedAt + SAFARI_IME_ENTER_WINDOW_MS,
      }),
    ).toBe(false);
  });
});

describe("shouldCancelImeEnter", () => {
  it("does not cancel Enter while the IME session is still open", () => {
    expect(
      shouldCancelImeEnter(
        { isComposing: true, keyCode: 13 },
        { composing: false, compositionEndedAt: 1_000, now: 1_010 },
      ),
    ).toBe(false);
    expect(
      shouldCancelImeEnter(plainEnter, {
        composing: true,
        compositionEndedAt: 1_000,
        now: 1_010,
      }),
    ).toBe(false);
  });

  it("cancels the leftover Enter after compositionend so it does not insert a newline", () => {
    expect(
      shouldCancelImeEnter(plainEnter, {
        composing: false,
        compositionEndedAt: 1_000,
        now: 1_010,
      }),
    ).toBe(true);
  });
});

describe("blockImeEnter", () => {
  it("leaves a normal Enter for the caller to submit", () => {
    const event = enterEvent(plainEnter);
    expect(blockImeEnter(event, idle)).toBe(false);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("blocks Enter during an open composition without dropping the candidate", () => {
    const event = enterEvent({ isComposing: true, keyCode: 13 });
    expect(blockImeEnter(event, idle)).toBe(true);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("blocks and cancels the leftover Enter Safari fires after compositionend", () => {
    const event = enterEvent(plainEnter);
    expect(
      blockImeEnter(event, {
        composing: false,
        compositionEndedAt: 1_000,
        now: 1_010,
      }),
    ).toBe(true);
    expect(event.preventDefault).toHaveBeenCalledOnce();
  });

  it("blocks Shift+Enter during that window without cancelling the newline", () => {
    const event = enterEvent(plainEnter, true);
    expect(
      blockImeEnter(event, {
        composing: false,
        compositionEndedAt: 1_000,
        now: 1_010,
      }),
    ).toBe(true);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});

describe("handleInputKeyDown", () => {
  it("submits a normal Enter and blocks the newline", () => {
    const event = enterEvent(plainEnter);
    const onSubmit = vi.fn();

    handleInputKeyDown(event, idle, onSubmit);

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("does not submit Enter that confirms an IME candidate", () => {
    const event = enterEvent({ isComposing: true, keyCode: 13 });
    const onSubmit = vi.fn();

    handleInputKeyDown(event, idle, onSubmit);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("does not submit the leftover Safari Enter", () => {
    const event = enterEvent(plainEnter);
    const onSubmit = vi.fn();

    handleInputKeyDown(
      event,
      { composing: false, compositionEndedAt: 1_000, now: 1_010 },
      onSubmit,
    );

    expect(onSubmit).not.toHaveBeenCalled();
    expect(event.preventDefault).toHaveBeenCalledOnce();
  });

  it("leaves Shift+Enter as a newline", () => {
    const event = enterEvent(plainEnter, true);
    const onSubmit = vi.fn();

    handleInputKeyDown(event, idle, onSubmit);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});
