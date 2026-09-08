"use client";

import { AnimatePresence, motion } from "motion/react";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";

export default function Nudges({
  nudges,
  onboarding,
  handleSuggestionClick,
}: {
  nudges: string[];
  onboarding?: boolean;
  handleSuggestionClick: (suggestion: string) => void;
}) {
  const isCloudBrand = useIsCloudBrand();

  return (
    <div className="flex-shrink-0 w-full">
      <AnimatePresence>
        {nudges.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            transition={{
              duration: 0.2,
              ease: "easeInOut",
            }}
          >
            <div className="flex flex-wrap gap-2 justify-start">
              {nudges.map((suggestion: string, index: number) => (
                <button
                  type="button"
                  key={index}
                  data-testid={`suggestion-${index}`}
                  onClick={() => handleSuggestionClick(suggestion)}
                  className={cn(
                    onboarding || isCloudBrand
                      ? "text-foreground"
                      : "text-placeholder-foreground hover:text-foreground",
                    "ibm-chat-bubble bg-background border hover:bg-background/50 px-2 py-1.5 rounded-lg text-sm transition-colors whitespace-nowrap",
                  )}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
