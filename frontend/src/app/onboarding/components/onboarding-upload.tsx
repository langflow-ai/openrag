import { AnimatePresence, motion } from "motion/react";
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { useGetNudgesQuery } from "@/app/api/queries/useGetNudgesQuery";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import { AnimatedProviderSteps } from "@/app/onboarding/components/animated-provider-steps";
import { Button } from "@/components/ui/button";
import { uploadFile } from "@/lib/upload-utils";

interface OnboardingUploadProps {
  onComplete: () => void;
}

const OnboardingUpload = ({ onComplete }: OnboardingUploadProps) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [currentStep, setCurrentStep] = useState<number | null>(null);

  const STEP_LIST = [
    "Uploading your document",
    "Generating embeddings",
    "Ingesting document",
    "Processing your document",
  ];

  // Query tasks to track completion
  const { data: tasks } = useGetTasksQuery({
    enabled: currentStep !== null, // Only poll when upload has started
    refetchInterval: currentStep !== null ? 1000 : false, // Poll every 1 second during upload
  });

  const { refetch: refetchNudges } = useGetNudgesQuery(null);

  // Monitor tasks and call onComplete when file processing is done
  useEffect(() => {
    if (currentStep === null || !tasks) {
      return;
    }

    // Check if there are any active tasks (pending, running, or processing)
    const activeTasks = tasks.find(
      (task) =>
        task.status === "pending" ||
        task.status === "running" ||
        task.status === "processing",
    );

    // If no active tasks and we have more than 1 task (initial + new upload), complete it
    if (
      (!activeTasks || (activeTasks.processed_files ?? 0) > 0) &&
      tasks.length > 1
    ) {
      // Set to final step to show "Done"
      setCurrentStep(STEP_LIST.length);

      // Refetch nudges to get new ones
      refetchNudges();

      // Wait a bit before completing
      setTimeout(() => {
        onComplete();
      }, 1000);
    }
  }, [tasks, currentStep, onComplete, refetchNudges]);

  const resetFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const performUpload = async (file: File) => {
    setIsUploading(true);
    try {
      setCurrentStep(0);
      await uploadFile(file, true);
      console.log("Document upload task started successfully");
      // Move to processing step - task monitoring will handle completion
      setTimeout(() => {
        setCurrentStep(1);
      }, 1500);
    } catch (error) {
      console.error("Upload failed", (error as Error).message);
      // Reset on error
      setCurrentStep(null);
    } finally {
      setIsUploading(false);
    }
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) {
      resetFileInput();
      return;
    }

    try {
      await performUpload(selectedFile);
    } catch (error) {
      console.error(
        "Unable to prepare file for upload",
        (error as Error).message,
      );
    } finally {
      resetFileInput();
    }
  };

  return (
    <AnimatePresence mode="wait">
      {currentStep === null ? (
        <motion.div
          key="user-ingest"
          initial={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -24 }}
          transition={{ duration: 0.4, ease: "easeInOut" }}
        >
          <Button
            size="sm"
            variant="outline"
            onClick={handleUploadClick}
            disabled={isUploading}
          >
            <div>{isUploading ? "Uploading..." : "Add a document"}</div>
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleFileChange}
            className="hidden"
            accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
          />
        </motion.div>
      ) : (
        <motion.div
          key="ingest-steps"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: "easeInOut" }}
        >
          <AnimatedProviderSteps
            currentStep={currentStep}
            setCurrentStep={setCurrentStep}
            isCompleted={false}
            steps={STEP_LIST}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default OnboardingUpload;
