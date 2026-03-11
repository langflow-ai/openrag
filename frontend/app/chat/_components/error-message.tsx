import { AlertCircle } from "lucide-react";
import { motion } from "motion/react";
import DogIcon from "@/components/icons/dog-icon";
import { Message } from "./message";

interface ErrorMessageProps {
  content: string;
  animate?: boolean;
  delay?: number;
}

export function ErrorMessage({
  content,
  animate = true,
  delay = 0.2,
}: ErrorMessageProps) {
  return (
    <motion.div
      initial={animate ? { opacity: 0, y: -20 } : { opacity: 1, y: 0 }}
      animate={{ opacity: 1, y: 0 }}
      transition={
        animate
          ? { duration: 0.4, delay: delay, ease: "easeOut" }
          : { duration: 0 }
      }
    >
      <Message
        icon={
          <div className="w-8 h-8 flex items-center justify-center flex-shrink-0 select-none">
            <DogIcon
              className="h-6 w-6 transition-colors duration-300"
              disabled={false}
            />
          </div>
        }
      >
        <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm text-destructive font-medium mb-1">Error</p>
              <p className="text-sm text-muted-foreground">{content}</p>
            </div>
          </div>
        </div>
      </Message>
    </motion.div>
  );
}

// Made with Bob
