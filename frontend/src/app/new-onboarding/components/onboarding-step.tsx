import { AnimatePresence, motion } from "motion/react";
import { type ReactNode, useEffect, useState } from "react";
import { Message } from "@/app/chat/components/message";
import DogIcon from "@/components/logo/dog-icon";
import { AnimatedProcessingIcon } from "@/components/ui/animated-processing-icon";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { cn } from "@/lib/utils";

interface OnboardingStepProps {
  text: string;
  children?: ReactNode;
  isVisible: boolean;
  isCompleted?: boolean;
  icon?: ReactNode;
  isMarkdown?: boolean;
  hideIcon?: boolean;
  isLoadingModels?: boolean;
  loadingStatus?: string[];
}

export function OnboardingStep({
  text,
  children,
  isVisible,
  isCompleted = false,
  icon,
  isMarkdown = false,
  hideIcon = false,
  isLoadingModels = false,
  loadingStatus = [],
}: OnboardingStepProps) {
  const [displayedText, setDisplayedText] = useState("");
  const [showChildren, setShowChildren] = useState(false);
  const [currentStatusIndex, setCurrentStatusIndex] = useState<number>(0);

  // Cycle through loading status messages once
  useEffect(() => {
    if (!isLoadingModels || loadingStatus.length === 0) {
      setCurrentStatusIndex(0);
      return;
    }

    const interval = setInterval(() => {
      setCurrentStatusIndex((prev) => {
        const nextIndex = prev + 1;
        // Stop at the last message
        if (nextIndex >= loadingStatus.length - 1) {
          clearInterval(interval);
          return loadingStatus.length - 1;
        }
        return nextIndex;
      });
    }, 1500); // Change status every 1.5 seconds

    return () => clearInterval(interval);
  }, [isLoadingModels, loadingStatus]);

  useEffect(() => {
    if (!isVisible) {
      setDisplayedText("");
      setShowChildren(false);
      return;
    }

    if (isCompleted) {
      setDisplayedText(text);
      setShowChildren(true);
      return;
    }

    let currentIndex = 0;
    setDisplayedText("");
    setShowChildren(false);

    const interval = setInterval(() => {
      if (currentIndex < text.length) {
        setDisplayedText(text.slice(0, currentIndex + 1));
        currentIndex++;
      } else {
        clearInterval(interval);
        setShowChildren(true);
      }
    }, 20); // 20ms per character

    return () => clearInterval(interval);
  }, [text, isVisible, isCompleted]);

  if (!isVisible) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.4, ease: "easeOut" }}
      className={isCompleted ? "opacity-50" : ""}
    >
      <Message
        icon={
          hideIcon ? (
            <div className="w-8 h-8 rounded-lg flex-shrink-0" />
          ) : (
            icon || (
              <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center flex-shrink-0 select-none">
                <DogIcon
                  className="h-6 w-6 text-accent-foreground transition-colors duration-300"
                  disabled={isCompleted}
                />
              </div>
            )
          )
        }
      >
        <div>
          {isLoadingModels && loadingStatus.length > 0 ? (
            <div className="flex flex-col gap-2 py-1.5">
              <div className="flex items-center gap-2">
                <div className="relative w-1.5 h-2.5">
                  <AnimatedProcessingIcon className="text-current shrink-0 absolute inset-0" />
                </div>
                <span className="text-mmd font-medium text-muted-foreground">
                  Thinking
                </span>
              </div>
              <div className="overflow-hidden">
                <div className="flex items-center gap-5 overflow-y-hidden relative h-6">
                  <div className="w-px h-6 bg-border" />
                  <div className="relative h-5 w-full">
                    <AnimatePresence mode="sync" initial={false}>
                      <motion.span
                        key={currentStatusIndex}
                        initial={{ y: 24, opacity: 0 }}
                        animate={{ y: 0, opacity: 1 }}
                        exit={{ y: -24, opacity: 0 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className="text-mmd font-medium text-primary absolute left-0"
                      >
                        {loadingStatus[currentStatusIndex]}
                      </motion.span>
                    </AnimatePresence>
                  </div>
                </div>
              </div>
            </div>
          ) : isMarkdown ? (
              <MarkdownRenderer
                className={cn(
                  isCompleted
                    ? "text-placeholder-foreground"
                    : "text-foreground",
                  "text-sm py-1.5 transition-colors duration-300",
                )}
                chatMessage={text}
              />
          ) : (
            <div className="flex flex-col gap-2 py-1.5">
              <p
                className={`text-foreground text-sm transition-colors duration-300 ${
                  isCompleted ? "text-placeholder-foreground" : ""
                }`}
              >
                {displayedText}
                {!showChildren && !isCompleted && (
                  <span className="inline-block w-1 h-3.5 bg-primary ml-1 animate-pulse" />
                )}
              </p>
              <div className="h-6" />
            </div>
          )}
          {children && (
            <AnimatePresence>
              {((showChildren && !isCompleted) || isMarkdown) && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.3, delay: 0.3, ease: "easeOut" }}
                >
                  <div className="pt-2">
                  {children}</div>
                </motion.div>
              )}
            </AnimatePresence>
          )}
        </div>
      </Message>
    </motion.div>
  );
}
