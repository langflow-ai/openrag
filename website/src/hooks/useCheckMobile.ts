"use client";

// Dependencies
import { useEffect, useState } from "react";

/**
 * Checks if the current window is compatible with a mobile screen.
 *
 * @param {number} breakpoint The maximum window width to consider it a mobile
 *     screen. Defaults to `768`.
 * @returns {{ isMobile: boolean, isChecking: boolean }}
 */
const useCheckMobile = (
  breakpoint = 768,
): { isMobile: boolean; isChecking: boolean; width: number } => {
  // Local states
  const [width, setWidth] = useState<number>(0);
  const [isChecking, setIsChecking] = useState<boolean>(true);

  // Handlers
  const handleWindowSizeChange = () => {
    setWidth(window.innerWidth);
    setIsChecking(false);
  };

  // Effects
  useEffect(() => {
    handleWindowSizeChange();
    window.addEventListener("resize", handleWindowSizeChange);
    return () => {
      window.removeEventListener("resize", handleWindowSizeChange);
    };
  }, []);

  return { isMobile: width <= breakpoint, isChecking, width };
};

export default useCheckMobile;
