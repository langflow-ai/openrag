// Dependencies
import {
  ElementType,
  forwardRef,
  HTMLAttributes,
  JSX,
  PropsWithChildren,
} from "react";

// Types
import { Size, SizeRecord, Weight } from "./types";

// Utilities
import { getLargerSize, getSizesFromObject, getTagNameFromSize } from "./utils";
import { buildClassName } from "@/lib/utils/style";

// Styles
import styles from "./styles.module.scss";

// Props types
type Props = PropsWithChildren<
  HTMLAttributes<HTMLElement> & {
    /**
     * The component size.
     */
    size: Size | SizeRecord;
    /**
     * The element tag name to use when rendering the component. Defaults to a
     * calculated heading tag (`h1`-`h6`) based on the value of the `size`
     * property.
     */
    tagName?: ElementType;
    /**
     * The component weight.
     */
    weight?: Weight;
    /**
     * Whether the component should be smaller on mobile using default sm sizes.
     * @default true
     */
    smallerOnMobile?: boolean;
  }
>;

/**
 * The Display component.
 *
 * This component implements a heading using the **Display** styling. The
 * default behavior is to render a HTML heading element (`h1`-`h6`) depending
 * on the value of the `size` property but a different HTML element may be
 * provided through the `tagName` property.
 *
 * Usage:
 *
 * ```
 * <Display size={800}>Lorem Ipsum</Display>
 * ```
 *
 * @param {Props} props
 * @returns {JSX.Element}
 */
const Display = forwardRef<HTMLElement, Props>(
  (
    {
      children,
      className,
      size,
      smallerOnMobile = true,
      tagName,
      weight = Weight.Semibold,
      ...props
    },
    ref,
  ): JSX.Element => {
    // Variables
    const biggestSize: Size = getLargerSize(size);
    const Element = tagName || getTagNameFromSize(biggestSize);
    const classes = buildClassName({
      [styles.display]: true,
      [styles[`display--size-${size}`]]: typeof size === "number",
      [styles["display--sm-size"]]: !!smallerOnMobile,
      [styles[`display--weight-${weight}`]]: true,
      [getSizesFromObject(size, styles)]: typeof size === "object",
      [className || ""]: !!className,
    });

    return (
      <Element className={classes} ref={ref} {...props}>
        {children}
      </Element>
    );
  },
);

Display.displayName = "Display";

export default Display;
