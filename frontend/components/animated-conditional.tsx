import { motion } from "framer-motion";
import { ANIMATION_DURATION } from "@/lib/constants";

export const AnimatedConditional = ({
  children,
  isOpen,
  className,
  slide = false,
  delay,
  duration,
  vertical = false,
}: {
  children: React.ReactNode;
  isOpen: boolean;
  className?: string;
  delay?: number;
  duration?: number;
  vertical?: boolean;
  slide?: boolean;
}) => {
  const animationProperty = slide
    ? vertical
      ? "translateY"
      : "translateX"
    : vertical
      ? "height"
      : "width";
  const animationValue = isOpen
    ? slide
      ? "0px"
      : "auto"
    : slide
      ? "-100%"
      : "0px";

  return (
    <motion.div
      initial={{ [animationProperty]: animationValue }}
      animate={{ [animationProperty]: animationValue }}
      exit={{ [animationProperty]: 0 }}
      transition={{
        duration: duration ?? ANIMATION_DURATION,
        ease: "easeOut",
        delay: delay,
      }}
      style={{
        overflow: "hidden",
        whiteSpace: vertical ? "normal" : "nowrap",
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
};
