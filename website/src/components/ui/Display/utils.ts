// Dependencies
import { ElementType } from "react";

// Types
import { Size, SizeRecord } from "./types";
import { CSSModule } from "@/lib/types/definitions";

/**
 * Get the tag name given the component size.
 *
 * @param {Size} size
 * @returns {ElementType}
 */
export const getTagNameFromSize = (size: Size): ElementType => {
  switch (size) {
    case 10:
    case 20:
    case 30:
    case 100:
    case 150:
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

/**
 * Get the larger size from a size or a breakpoint-size map.
 * If a breakpoint-size map is provided, the largest size is returned.
 * If a single size is provided, the size is returned.
 *
 *
 * @param {Size | SizeRecord} size
 * @returns {Size} The larger size.
 */
export const getLargerSize = (size: Size | SizeRecord): Size => {
  if (typeof size === "number") {
    return size;
  }

  return Math.max(...Object.values(size)) as Size;
};

export const getSizesFromObject = (
  size: Size | SizeRecord,
  styles: CSSModule,
): string => {
  if (typeof size === "number") return ``;
  const classes: string[] = [];

  Object.entries(size).forEach(([breakpoint, sizeValue]) => {
    classes.push(styles[`display--size--${breakpoint}-${sizeValue}`]);
  });

  return classes.join(" ");
};
