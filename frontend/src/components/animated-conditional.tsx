import { motion } from "framer-motion";

export const AnimatedConditional = ({
  children,
  isOpen,
  className,
  delay,
  vertical = false,
}: {
  children: React.ReactNode;
  isOpen: boolean;
  className?: string;
  delay?: number; 
  vertical?: boolean;
}) => {
  const animationProperty = vertical ? "height" : "width";
  const animationValue = isOpen ? "auto" : 0;

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
