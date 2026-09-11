import { useEffect, useRef, useState } from "react";

/**
 * Typewrite a string one character at a time.
 * When `active` is true the string is revealed character-by-character at
 * `speed` ms per character; when false the full string is displayed immediately.
 * `onDone` fires once when the animation completes.
 */
export function useTypewriter(
  text: string,
  active: boolean,
  onDone?: () => void,
  speed = 28,
) {
  const [displayed, setDisplayed] = useState(active ? "" : text);
  const frameRef = useRef<NodeJS.Timeout | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (frameRef.current) {
      clearTimeout(frameRef.current);
      frameRef.current = null;
    }
    if (!active) {
      setDisplayed(text);
      return;
    }
    setDisplayed("");
    let i = 0;
    const tick = () => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i < text.length) {
        frameRef.current = setTimeout(tick, speed);
      } else {
        onDoneRef.current?.();
      }
    };
    frameRef.current = setTimeout(tick, speed);
    return () => {
      if (frameRef.current) {
        clearTimeout(frameRef.current);
        frameRef.current = null;
      }
    };
  }, [text, active, speed]);

  return displayed;
}
