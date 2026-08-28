// Dependencies
import {
  ElementType,
  forwardRef,
  HTMLAttributes,
  JSX,
  PropsWithChildren,
} from "react";

// Types
import { Size, Weight } from "./types";

// Utilities
import { getTagNameFromSize } from "./utils";

// Styles
import styles from "./styles.module.scss";

// Props types
type Props = PropsWithChildren<
  HTMLAttributes<HTMLElement> & {
    /**
     * The component size.
     */
    size: Size;
    /**
     * The element tag name to use when rendering the component. Defaults to a
     * calculated heading or paragraph tag (`h1`-`h6`, or `p`) based on the
     * value of the `size` property.
     */
    tagName?: ElementType;
    /**
     * The component weight.
     */
    weight?: Weight;
    /**
     * Toggle this value if the current `size` is smaller on mobile.
     */
    mobileSmall?: boolean;
    /**
     * Toggle this value if the font family needs to be Chivo.
     */
    chivo?: boolean;
  }
>;

/**
 * The Text component.
 *
 * This component implements a heading using the **Text** styling. The default
 * behavior is to render a HTML heading (`h1`-`h6`) or paragraph (`p`) element
 * depending on the value of the `size` property but a different HTML element
 * may be provided through the `tagName` property.
 *
 * Usage:
 *
 * ```
 * <Text size={700}>Lorem Ipsum</Text>
 * ```
 *
 * @param {Props} props
 * @returns {JSX.Element}
 */

const Text = forwardRef<HTMLElement, Props>(
  (
    {
      children,
      className,
      mobileSmall,
      size,
      tagName,
      weight = Weight.Regular,
      chivo,
      ...props
    },
    ref,
  ): JSX.Element => {
    // Variables
    const Element = tagName || getTagNameFromSize(size);
    const classes = `${styles.text} ${styles[`text--size-${size}`]} ${
      styles[`text--weight-${weight}`]
    } ${chivo ? styles[`text--chivo`] : ""} ${className || ""} ${
      mobileSmall ? styles["mobile-small"] : ""
    }`.trim();

    return (
      <Element className={classes} ref={ref} {...props}>
        {children}
      </Element>
    );
  },
);

Text.displayName = "Text";

export default Text;
