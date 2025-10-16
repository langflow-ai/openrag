import { motion } from "framer-motion";

export const AnimatedConditional = ({
  children,
  isOpen,
  className,
  grow = true,
  delay,
  vertical = false,
}: {
  children: React.ReactNode;
  isOpen: boolean;
  className?: string;
  delay?: number; 
  vertical?: boolean;
  grow?: boolean;
}) => {
  const animationProperty = grow ? (vertical ? "height" : "width") : (vertical ? "translateY" : "translateX");
  const animationValue = isOpen ? (grow ? "auto" : "0") : (grow ? 0 : "-100%");

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
