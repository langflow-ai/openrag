import { useCallback, useRef } from "react";
import {
  blockImeEnter,
  handleInputKeyDown,
  type ImeCompositionState,
  type ImeEnterEvent,
  type ImeKeyEvent,
  isImeCompositionEvent,
  shouldCancelImeEnter,
} from "@/lib/ime-composition";

/**
 * Tracks an IME composition session for one text field and submits on Enter.
 *
 * ```tsx
 * const ime = useImeComposition(onSubmit);
 * <textarea {...ime.inputProps} />
 * ```
 *
 * A field that also handles other keys calls `handleKeyDown` after its own
 * logic. `isImeCandidateKey` is for keys that cycle a candidate, such as
 * Space. A space after composition ends is a real space, so that check
 * ignores Safari's Enter window.
 */
export function useImeComposition(onSubmit?: () => void) {
  const onSubmitRef = useRef(onSubmit);
  onSubmitRef.current = onSubmit;
  const isComposingRef = useRef(false);
  const compositionEndedAtRef = useRef(0);

  const readState = useCallback((): ImeCompositionState => {
    const compositionEndedAt = compositionEndedAtRef.current;
    return {
      composing: isComposingRef.current,
      compositionEndedAt,
      now: compositionEndedAt > 0 ? performance.now() : 0,
    };
  }, []);

  const onCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const onCompositionEnd = useCallback(() => {
    isComposingRef.current = false;
    compositionEndedAtRef.current = performance.now();
  }, []);

  const onBlur = useCallback(() => {
    isComposingRef.current = false;
    compositionEndedAtRef.current = 0;
  }, []);

  // Safari's confirming Enter is identified by time since compositionend.
  // Consume that window on the first Enter so a second press can send.
  const releaseSafariEnter = useCallback(
    (event: ImeEnterEvent, state: ImeCompositionState) => {
      if (
        event.key === "Enter" &&
        shouldCancelImeEnter(event.nativeEvent, state)
      ) {
        compositionEndedAtRef.current = 0;
      }
    },
    [],
  );

  const blockEnter = useCallback(
    (event: ImeEnterEvent, state?: ImeCompositionState) => {
      const snapshot = state ?? readState();
      const blocked = blockImeEnter(event, snapshot);
      if (blocked) releaseSafariEnter(event, snapshot);
      return blocked;
    },
    [readState, releaseSafariEnter],
  );

  const isImeCandidateKey = useCallback((event: ImeKeyEvent) => {
    return isImeCompositionEvent(event, {
      composing: isComposingRef.current,
      compositionEndedAt: 0,
    });
  }, []);

  const handleKeyDown = useCallback(
    (event: ImeEnterEvent) => {
      const state = readState();
      handleInputKeyDown(event, state, () => onSubmitRef.current?.());
      releaseSafariEnter(event, state);
    },
    [readState, releaseSafariEnter],
  );

  return {
    inputProps: {
      onCompositionStart,
      onCompositionEnd,
      onBlur,
      onKeyDown: handleKeyDown,
    },
    readState,
    blockEnter,
    isImeCandidateKey,
    handleKeyDown,
  };
}
