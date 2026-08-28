"use client";

// Dependencies
import Image, { ImageProps } from "next/image";
import { JSX, useState } from "react";

// Utilities
import { loader } from "./utils";

/**
 *
 * @param {ImageProps} props
 * @returns {JSX.Element}
 */

const StaticImage = ({
  alt,
  fallback,
  src,
  ...props
}: ImageProps & {
  fallback?: string;
}): JSX.Element => {
  const [hasError, setHasError] = useState<boolean>(false);

  // Validations
  if (!props.height) {
    props.height = 0;
  }
  if (!props.width) {
    props.width = 0;
  }

  return (
    <Image
      alt={alt}
      loader={loader}
      src={hasError && fallback ? fallback : src}
      {...props}
      onError={() => setHasError(true)}
    />
  );
};

export default StaticImage;
