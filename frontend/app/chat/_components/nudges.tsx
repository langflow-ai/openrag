import { AnimatePresence, motion } from "motion/react";
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
  return (
    <div className="flex-shrink-0 h-12 w-full overflow-hidden">
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
            <div className="relative flex">
              <div className="w-full">
                <div className="flex gap-3 justify-start overflow-x-auto scrollbar-hide">
                  {nudges.map((suggestion: string, index: number) => (
                    <button
                      key={index}
                      onClick={() => handleSuggestionClick(suggestion)}
                      className={cn(
                        onboarding
                          ? "text-foreground"
                          : "text-placeholder-foreground hover:text-foreground",
                        "bg-background border hover:bg-background/50 px-2 py-1.5 rounded-lg text-sm transition-colors whitespace-nowrap",
                      )}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
                {/* Fade out gradient on the right */}
                <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-background to-transparent pointer-events-none"></div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
