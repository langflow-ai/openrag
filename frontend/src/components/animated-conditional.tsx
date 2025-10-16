import { motion } from "framer-motion";

export const AnimatedConditional = ({
  children,
  isOpen,
  className,
  slide = false,
  delay,
  vertical = false,
}: {
  children: React.ReactNode;
  isOpen: boolean;
  className?: string;
  delay?: number; 
  vertical?: boolean;
  slide?: boolean;
}) => {
  const animationProperty = slide ? (vertical ? "translateY" : "translateX") : (vertical ? "height" : "width");
  const animationValue = isOpen ? (slide ? "0px" : "auto") : (slide ? "-100%" : "0px");

  return (
    <motion.div
      initial={{ [animationProperty]: animationValue }}
      animate={{ [animationProperty]: animationValue }}
      exit={{ [animationProperty]: 0 }}
      transition={{
        duration: 0.4,
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
