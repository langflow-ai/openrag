import { describe, expect, it } from "vitest";
import {
  IME_PROCESS_KEY_CODE,
  isImeCompositionEvent,
  SAFARI_IME_ENTER_WINDOW_MS,
  shouldCancelImeEnter,
} from "./ime-composition";

const plainEnter = { isComposing: false, keyCode: 13 };
const idle = { composing: false, compositionEndedAt: 0, now: 1_000 };

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
