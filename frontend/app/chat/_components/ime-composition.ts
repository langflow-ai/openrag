/**
 * Detect Enter keystrokes that belong to an IME composition session
 * (Japanese, Chinese, Korean) so they confirm a candidate instead of
 * submitting chat or picking a knowledge filter.
 *
 * Chrome and Edge on macOS fire keydown with isComposing still true.
 * Firefox does not fire that keydown at all. Safari fires compositionend
 * first, so the confirming Enter arrives with isComposing already false
 * (https://bugs.webkit.org/show_bug.cgi?id=165004). That leftover keydown
 * is a few milliseconds after compositionend; a deliberate send is not.
 */

/** IME processing key. Never produced by a physical key. */
export const IME_PROCESS_KEY_CODE = 229;

/** Window that covers Safari's post-compositionend Enter, not a human keypress. */
export const SAFARI_IME_ENTER_WINDOW_MS = 50;

export type ImeKeyEvent = {
  isComposing: boolean;
  keyCode: number;
};

export type ImeCompositionState = {
  composing: boolean;
  compositionEndedAt: number;
  now?: number;
};

const IDLE_STATE: ImeCompositionState = {
  composing: false,
  compositionEndedAt: 0,
};

function isWithinSafariImeWindow(state: ImeCompositionState): boolean {
  if (state.compositionEndedAt <= 0) return false;
  const now = state.now ?? performance.now();
  const elapsed = now - state.compositionEndedAt;
  return elapsed >= 0 && elapsed < SAFARI_IME_ENTER_WINDOW_MS;
}

export function isImeCompositionEvent(
  event: ImeKeyEvent,
  state: ImeCompositionState = IDLE_STATE,
): boolean {
  if (
    event.isComposing ||
    state.composing ||
    event.keyCode === IME_PROCESS_KEY_CODE
  ) {
    return true;
  }
  return isWithinSafariImeWindow(state);
}

/**
 * The Enter that follows compositionend is an ordinary key to the textarea
 * and would insert a newline. Cancelling it while the IME is still open
 * drops the candidate, so only the leftover post-composition key is cancelled.
 */
export function shouldCancelImeEnter(
  event: ImeKeyEvent,
  state: ImeCompositionState,
): boolean {
  if (event.isComposing || state.composing) return false;
  return isWithinSafariImeWindow(state);
}
