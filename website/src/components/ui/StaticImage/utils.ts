// Dependencies
import { ImageLoaderProps } from "next/image";

/**
 * The loader for static images.
 *
 * This loader function simply returns the image source path as is.
 *
 * @param {ImageLoaderProps} props
 * @returns {string}
 */
export const loader = ({ src, width, quality }: ImageLoaderProps): string => {
  if (/^(?:[a-z]+:)?\/\//i.test(src) || src.startsWith("data:")) {
    return src;
  }

  const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  const absoluteSrc = src.startsWith("/") ? src : `/${src}`;

  return `${basePath}${absoluteSrc}?w=${width}&q=${quality || 75}`;
};
