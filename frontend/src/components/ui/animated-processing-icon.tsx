import { cn } from "@/lib/utils";
import { motion, easeInOut } from "framer-motion";

export const AnimatedProcessingIcon = ({
  className,
}: {
  className?: string;
}) => {
  const createAnimationFrames = (delay: number) => ({
    opacity: [1, 1, 0.5, 0], // Opacity Steps
    transition: {
      delay,
      duration: 1,
      ease: easeInOut,
      repeat: Infinity,
      times: [0, 0.33, 0.66, 1], // Duration Percentages that Correspond to opacity Array
    },
  });

  return (
    <svg
      data-testid="rotating-dot-animation"
      className={cn("h-[10px] w-[6px]", className)}
      viewBox="0 0 6 10"
    >
      <motion.circle
        animate={createAnimationFrames(0)}
        fill="currentColor"
        cx="1"
        cy="1"
        r="1"
      />
      <motion.circle
        animate={createAnimationFrames(0.16)}
        fill="currentColor"
        cx="1"
        cy="5"
        r="1"
      />
      <motion.circle
        animate={createAnimationFrames(0.33)}
        fill="currentColor"
        cx="1"
        cy="9"
        r="1"
      />
      <motion.circle
        animate={createAnimationFrames(0.83)}
        fill="currentColor"
        cx="5"
        cy="1"
        r="1"
      />
      <motion.circle
        animate={createAnimationFrames(0.66)}
        fill="currentColor"
        cx="5"
        cy="5"
        r="1"
      />
      <motion.circle
        animate={createAnimationFrames(0.5)}
        fill="currentColor"
        cx="5"
        cy="9"
        r="1"
      />
    </svg>
  );
};
