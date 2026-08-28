// Dependencies
import { ElementType } from "react";

// Types
import { Size } from "./types";

/**
 * Get the tag name given the component size.
 *
 * @param {Size} size
 * @returns {ElementType}
 */
export const getTagNameFromSize = (size: Size): ElementType => {
  switch (size) {
    case 100:
      return "p";
    case 200:
      return "h6";
    case 300:
      return "h5";
    case 400:
      return "h4";
    case 500:
      return "h3";
    case 600:
      return "h2";
    case 700:
      return "h1";
  }
};
