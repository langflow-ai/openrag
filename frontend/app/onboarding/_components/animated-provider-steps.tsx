"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckIcon, XIcon } from "lucide-react";
import { useEffect, useState } from "react";
import AnimatedProcessingIcon from "@/components/icons/animated-processing-icon";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { cn } from "@/lib/utils";

export function AnimatedProviderSteps({
  currentStep,
  isCompleted,
  setCurrentStep,
  steps,
  processingStartTime,
  hasError = false,
}: {
  currentStep: number;
  isCompleted: boolean;
  setCurrentStep: (step: number) => void;
  steps: string[];
  processingStartTime?: number | null;
  hasError?: boolean;
}) {
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsedTime, setElapsedTime] = useState<number>(0);

  // Initialize start time from prop
  useEffect(() => {
    if (processingStartTime) {
      // Use the start time passed from parent (when user clicked Complete)
      setStartTime(processingStartTime);
    }
  }, [processingStartTime]);

  // Progress through steps
  useEffect(() => {
    if (currentStep < steps.length - 1 && !isCompleted) {
      const interval = setInterval(() => {
        setCurrentStep(currentStep + 1);
      }, 1500);
      return () => clearInterval(interval);
    }
  }, [currentStep, setCurrentStep, steps, isCompleted]);

  // Calculate elapsed time when completed
  useEffect(() => {
    if (isCompleted && startTime) {
      const elapsed = Date.now() - startTime;
      setElapsedTime(elapsed);
    }
  }, [isCompleted, startTime]);

  const isDone = currentStep >= steps.length && !isCompleted && !hasError;

  return (
    <AnimatePresence mode="wait">
      {!isCompleted ? (
        <motion.div
          key="processing"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          className="flex flex-col gap-2"
        >
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "transition-all duration-300 relative",
                isDone || hasError ? "w-3.5 h-3.5" : "w-6 h-6",
              )}
            >
              <CheckIcon
                className={cn(
                  "text-accent-emerald-foreground shrink-0 w-3.5 h-3.5 absolute inset-0 transition-all duration-150",
                  isDone ? "opacity-100" : "opacity-0",
                )}
              />
              <XIcon
                className={cn(
                  "text-accent-red-foreground shrink-0 w-3.5 h-3.5 absolute inset-0 transition-all duration-150",
                  hasError ? "opacity-100" : "opacity-0",
                )}
              />
              <AnimatedProcessingIcon
                className={cn(
                  "text-current shrink-0 absolute inset-0 transition-all duration-150",
                  isDone || hasError ? "opacity-0" : "opacity-100",
                )}
              />
            </div>

            <span className="!text-mmd font-medium text-muted-foreground">
              {hasError ? "Error" : isDone ? "Done" : "Thinking"}
            </span>
          </div>
          <div className="overflow-hidden">
            <AnimatePresence>
              {!isDone && !hasError && (
                <motion.div
                  initial={{ opacity: 1, y: 0, height: "auto" }}
                  exit={{ opacity: 0, y: -24, height: 0 }}
                  transition={{ duration: 0.4, ease: "easeInOut" }}
                  className="flex items-center gap-4 overflow-y-hidden relative h-6"
                >
                  <div className="w-px h-6 bg-border ml-3" />
                  <div className="relative h-5 w-full">
                    <AnimatePresence mode="sync" initial={false}>
                      <motion.span
                        key={currentStep}
                        initial={{ y: 24, opacity: 0 }}
                        animate={{ y: 0, opacity: 1 }}
                        exit={{ y: -24, opacity: 0 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className="text-mmd font-medium text-primary absolute left-0"
                      >
                        {steps[currentStep]}
                      </motion.span>
                    </AnimatePresence>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      ) : (
        <motion.div
          key="completed"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
        >
          <Accordion type="single" collapsible>
            <AccordionItem value="steps" className="border-none">
              <AccordionTrigger className="hover:no-underline p-0 py-2">
                <div className="flex items-center gap-2">
                  <span className="text-mmd font-medium text-muted-foreground">
                    {`Initialized in ${(elapsedTime / 1000).toFixed(1)} seconds`}
                  </span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="pl-0 pt-2 pb-0">
                <div className="relative pl-1">
                  {/* Connecting line on the left */}
                  <motion.div
                    className="absolute left-[7px] top-0 bottom-0 w-px bg-border z-0"
                    initial={{ scaleY: 0 }}
                    animate={{ scaleY: 1 }}
                    transition={{ duration: 0.3, ease: "easeOut" }}
                    style={{ transformOrigin: "top" }}
                  />

                  <div className="space-y-3 ml-4">
                    <AnimatePresence>
                      {steps.map((step, index) => (
                        <motion.div
                          key={step}
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{
                            duration: 0.3,
                            delay: index * 0.05,
                          }}
                          className="flex items-center gap-1.5"
                        >
                          <motion.div
                            className="relative w-3.5 h-3.5 shrink-0 z-10 bg-background"
                            initial={{ scale: 0 }}
                            animate={{ scale: 1 }}
                            transition={{
                              duration: 0.2,
                              delay: index * 0.05 + 0.1,
                            }}
                          >
                            <motion.div
                              key="check"
                              initial={{ scale: 0, rotate: -180 }}
                              animate={{ scale: 1, rotate: 0 }}
                              transition={{ duration: 0.3 }}
                            >
                              <CheckIcon className="text-accent-emerald-foreground w-3.5 h-3.5" />
                            </motion.div>
                          </motion.div>
                          <span className="text-mmd text-muted-foreground">
                            {step}
                          </span>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
