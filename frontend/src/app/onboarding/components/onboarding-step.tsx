import { AnimatePresence, motion } from "motion/react";
import { type ReactNode, useEffect, useState } from "react";
import { Message } from "@/app/chat/components/message";
import DogIcon from "@/components/logo/dog-icon";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { cn } from "@/lib/utils";

interface OnboardingStepProps {
  text: string;
  children?: ReactNode;
  isVisible: boolean;
  isCompleted?: boolean;
  showCompleted?: boolean;
  icon?: ReactNode;
  isMarkdown?: boolean;
  hideIcon?: boolean;
}

export function OnboardingStep({
  text,
  children,
  isVisible,
  isCompleted = false,
  showCompleted = false,
  icon,
  isMarkdown = false,
  hideIcon = false,
}: OnboardingStepProps) {
  const [displayedText, setDisplayedText] = useState("");
  const [showChildren, setShowChildren] = useState(false);

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
              <div className="w-8 h-8 flex items-center justify-center flex-shrink-0 select-none">
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
          {isMarkdown ? (
            <MarkdownRenderer
              className={cn(
                isCompleted ? "text-placeholder-foreground" : "text-foreground",
                "text-sm py-1.5 transition-colors duration-300",
              )}
              chatMessage={text}
            />
          ) : (
            <p
              className={`text-foreground text-sm py-1.5 transition-colors duration-300 ${
                isCompleted ? "text-placeholder-foreground" : ""
              }`}
            >
              {displayedText}
              {!showChildren && !isCompleted && (
                <span className="inline-block w-1 h-3.5 bg-primary ml-1 animate-pulse" />
              )}
            </p>
          )}
          {children && (
            <AnimatePresence>
              {((showChildren && (!isCompleted || showCompleted)) ||
                isMarkdown) && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.3, delay: 0.3, ease: "easeOut" }}
                >
                  <div className="pt-4">{children}</div>
                </motion.div>
              )}
            </AnimatePresence>
          )}
        </div>
      </Message>
    </motion.div>
  );
}
