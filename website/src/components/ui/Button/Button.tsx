// Dependencies
import { ElementType, PropsWithChildren } from "react";

// Types
import { ButtonTypes } from "./types";

// Styles
import styles from "./styles.module.scss";

// Props
type Props = PropsWithChildren & {
  className?: string;
  type?: ButtonTypes;
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
};

const Button = ({
  className,
  type = ButtonTypes.PRIMARY,
  href,
  onClick,
  children,
  disabled = false,
}: Props) => {
  const Element: ElementType = href ? "a" : "button";

  const buttonClass = `${styles.button} ${styles[type]} ${className}`;

  return (
    <Element
      href={href}
      className={buttonClass}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </Element>
  );
};

export default Button;
