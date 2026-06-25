import { X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useCreateFilter } from "@/app/api/mutations/useCreateFilter";
import { useUpdateOnboardingStateMutation } from "@/app/api/mutations/useUpdateOnboardingStateMutation";
import { useGetNudgesQuery } from "@/app/api/queries/useGetNudgesQuery";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import { AnimatedProviderSteps } from "@/app/onboarding/_components/animated-provider-steps";
import { SUPPORTED_EXTENSIONS } from "@/components/knowledge-dropdown";
import { Button } from "@/components/ui/button";
import { trackButton } from "@/lib/analytics";
import { uploadFile } from "@/lib/upload-utils";

interface OnboardingUploadProps {
  onComplete: () => void;
}

const OnboardingUpload = ({ onComplete }: OnboardingUploadProps) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [currentStep, setCurrentStep] = useState<number | null>(null);
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const [uploadedTaskId, setUploadedTaskId] = useState<string | null>(null);
  const [shouldCreateFilter, setShouldCreateFilter] = useState(false);
  const [isCreatingFilter, setIsCreatingFilter] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createFilterMutation = useCreateFilter();
  const updateOnboardingMutation = useUpdateOnboardingStateMutation();

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
    let cancelled = false;
    let completeTimeoutId: NodeJS.Timeout;
    if (currentStep === null || !tasks || !uploadedTaskId) {
      return;
    }

    // Find the task by task ID from the upload response
    const matchingTask = tasks.find((task) => task.task_id === uploadedTaskId);

    // If no matching task found, wait for it to appear
    if (!matchingTask) {
      return;
    }

    // Check if the matching task is still active (pending, running, or processing)
    const isTaskActive =
      matchingTask.status === "pending" ||
      matchingTask.status === "running" ||
      matchingTask.status === "processing";

    // Check if matching task failed or has error status
    const failedTask =
      matchingTask.status === "failed" || matchingTask.status === "error";

    // Check if any file inside the task failed
    const filesArray = matchingTask.files
      ? (Object.values(matchingTask.files) as {
          status: string;
          error?: string;
        }[])
      : [];
    const hasFailedFile = filesArray.some(
      (file) => file.status === "failed" || file.status === "error",
    );

    if (failedTask || hasFailedFile) {
      let errorMessage = "Document ingestion failed. Please try again.";
      if (matchingTask.error) {
        errorMessage = matchingTask.error;
      } else {
        const failedFile = filesArray.find(
          (file) =>
            (file.status === "failed" || file.status === "error") && file.error,
        );
        if (failedFile?.error) {
          errorMessage = failedFile.error;
        }
      }

      setError(errorMessage);
      setCurrentStep(null);
      setUploadedTaskId(null);
      return;
    }

    // If task is completed or has processed files, complete the onboarding step
    if (!isTaskActive || (matchingTask.processed_files ?? 0) > 0) {
      // Set to final step to show "Done"
      setCurrentStep(STEP_LIST.length);

      // Create knowledge filter for uploaded document if requested
      // Guard against race condition: only create if not already creating
      if (shouldCreateFilter && uploadedFilename && !isCreatingFilter) {
        // Reset flags immediately (synchronously) to prevent duplicate creation
        setShouldCreateFilter(false);
        const filename = uploadedFilename;
        setUploadedFilename(null);
        setIsCreatingFilter(true);

        // Get display name from filename (remove extension for cleaner name)
        const displayName = filename.includes(".")
          ? filename.substring(0, filename.lastIndexOf("."))
          : filename;

        const queryData = JSON.stringify({
          query: "",
          filters: {
            data_sources: [filename],
            document_types: ["*"],
            owners: ["*"],
            connector_types: ["*"],
          },
          limit: 10,
          scoreThreshold: 0,
          color: "green",
          icon: "file",
        });

        // Wait for filter creation to complete before proceeding
        createFilterMutation
          .mutateAsync({
            name: displayName,
            description: `Filter for ${filename}`,
            queryData: queryData,
          })
          .then(async (result) => {
            if (result.filter?.id) {
              // Save to backend
              await updateOnboardingMutation.mutateAsync({
                user_doc_filter_id: result.filter.id,
              });

              console.log(
                "Created knowledge filter for uploaded document",
                result.filter.id,
              );
            }
          })
          .catch((error) => {
            console.error("Failed to create knowledge filter:", error);
          })
          .finally(() => {
            setIsCreatingFilter(false);
            // Refetch nudges to get new ones
            refetchNudges();

            // Wait a bit before completing (after filter is created)
            if (!cancelled) {
              completeTimeoutId = setTimeout(() => {
                if (!cancelled) onComplete();
              }, 1000);
            }
          });
      } else if (!isCreatingFilter) {
        // No filter to create, just complete
        // Refetch nudges to get new ones
        refetchNudges();

        // Wait a bit before completing
        if (!cancelled) {
          completeTimeoutId = setTimeout(() => {
            if (!cancelled) onComplete();
          }, 1000);
        }
      }
    }

    return () => {
      cancelled = true;
      clearTimeout(completeTimeoutId);
    };
  }, [
    tasks,
    currentStep,
    onComplete,
    refetchNudges,
    shouldCreateFilter,
    uploadedFilename,
    uploadedTaskId,
    createFilterMutation,
    isCreatingFilter,
  ]);

  const resetFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleUploadClick = () => {
    trackButton({
      CTA: "Add Data - Add a document",
      elementId: "upload-button",
      namespace: "onboarding",
    });
    fileInputRef.current?.click();
  };

  const performUpload = async (file: File) => {
    setIsUploading(true);
    setError(null);
    try {
      setCurrentStep(0);
      const result = await uploadFile(file, true, true); // Pass createFilter=true
      console.log("Document upload task started successfully");

      // Store task ID to track the specific upload task
      if (result.taskId) {
        setUploadedTaskId(result.taskId);
      }

      // Store filename and createFilter flag in state to create filter after ingestion succeeds
      if (result.createFilter && result.filename) {
        setUploadedFilename(result.filename);
        setShouldCreateFilter(true);
      }

      // Move to processing step - task monitoring will handle completion
      setTimeout(() => {
        setCurrentStep(1);
      }, 1500);
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : "Upload failed";
      console.error("Upload failed", errorMessage);
      setError(errorMessage);

      // Dispatch event that chat context can listen to
      // This avoids circular dependency issues
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("ingestionFailed", {
            detail: { source: "onboarding" },
          }),
        );
      }

      // Show error toast notification
      toast.error("Document upload failed", {
        description: errorMessage,
        duration: 5000,
      });

      // Reset on error
      setCurrentStep(null);
      setUploadedTaskId(null);
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
          <AnimatePresence mode="wait">
            {error && (
              <motion.div
                key="error"
                initial={{ opacity: 1, y: 0, height: "auto" }}
                exit={{ opacity: 0, y: -10, height: 0 }}
              >
                <div className="pb-6 flex items-center gap-4">
                  <X className="w-4 h-4 text-destructive shrink-0" />
                  <span
                    data-testid="onboarding-upload-error"
                    className="text-mmd text-muted-foreground"
                  >
                    {error}
                  </span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          <Button
            size="sm"
            variant="outline"
            data-testid="upload-button"
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
            accept={SUPPORTED_EXTENSIONS.join(",")}
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
