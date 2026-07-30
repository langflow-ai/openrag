import { X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useReducer,
  useRef,
} from "react";
import { toast } from "sonner";
import { useCreateFilter } from "@/app/api/mutations/useCreateFilter";
import { useUpdateOnboardingStateMutation } from "@/app/api/mutations/useUpdateOnboardingStateMutation";
import { useGetNudgesQuery } from "@/app/api/queries/useGetNudgesQuery";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import { AnimatedProviderSteps } from "@/app/onboarding/_components/animated-provider-steps";
import { IngestReviewDialog } from "@/components/ingest-review";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { trackButton } from "@/lib/analytics";
import {
  EMPTY_PREVIEW,
  isIngestPreviewEnabled,
  type PreviewDialogState,
} from "@/lib/ingest-preview";
import { SUPPORTED_EXTENSIONS } from "@/lib/supported-file-types";
import { uploadFile } from "@/lib/upload-utils";

interface OnboardingUploadProps {
  onComplete: () => void;
}

const STEP_LIST = [
  "Uploading your document",
  "Generating embeddings",
  "Ingesting document",
  "Processing your document",
];

type UploadState = {
  isUploading: boolean;
  currentStep: number | null;
  uploadedFilename: string | null;
  uploadedTaskId: string | null;
  shouldCreateFilter: boolean;
  isCreatingFilter: boolean;
  ingestionReady: boolean;
  error: string | null;
  preview: PreviewDialogState;
};

type UploadAction =
  | { type: "start_upload"; preview: PreviewDialogState | null }
  | { type: "set_step"; step: number | null }
  | { type: "set_preview"; preview: PreviewDialogState }
  | {
      type: "upload_succeeded";
      taskId: string | null;
      preview: PreviewDialogState | null;
      filename: string | null;
      createFilter: boolean;
    }
  | { type: "upload_failed"; error: string }
  | { type: "upload_finished" }
  | { type: "ingestion_failed"; error: string }
  | { type: "begin_create_filter"; filename: string }
  | { type: "finish_create_filter" }
  | { type: "mark_ingestion_ready" };

const initialUploadState: UploadState = {
  isUploading: false,
  currentStep: null,
  uploadedFilename: null,
  uploadedTaskId: null,
  shouldCreateFilter: false,
  isCreatingFilter: false,
  ingestionReady: false,
  error: null,
  preview: EMPTY_PREVIEW,
};

function uploadReducer(state: UploadState, action: UploadAction): UploadState {
  switch (action.type) {
    case "start_upload":
      return {
        ...state,
        isUploading: true,
        error: null,
        ingestionReady: false,
        preview: action.preview ?? state.preview,
      };
    case "set_step":
      return { ...state, currentStep: action.step };
    case "set_preview":
      return { ...state, preview: action.preview };
    case "upload_succeeded":
      return {
        ...state,
        uploadedTaskId: action.taskId ?? state.uploadedTaskId,
        preview: action.preview ?? state.preview,
        uploadedFilename: action.filename ?? state.uploadedFilename,
        shouldCreateFilter: action.createFilter
          ? true
          : state.shouldCreateFilter,
      };
    case "upload_failed":
      return {
        ...state,
        error: action.error,
        preview: EMPTY_PREVIEW,
        currentStep: null,
        uploadedTaskId: null,
      };
    case "upload_finished":
      return { ...state, isUploading: false };
    case "ingestion_failed":
      return {
        ...state,
        ingestionReady: false,
        error: action.error,
        currentStep: null,
        uploadedTaskId: null,
        preview: EMPTY_PREVIEW,
      };
    case "begin_create_filter":
      return {
        ...state,
        shouldCreateFilter: false,
        uploadedFilename: null,
        isCreatingFilter: true,
        currentStep: STEP_LIST.length,
      };
    case "finish_create_filter":
      return {
        ...state,
        isCreatingFilter: false,
        ingestionReady: true,
      };
    case "mark_ingestion_ready":
      return {
        ...state,
        currentStep: STEP_LIST.length,
        ingestionReady: true,
      };
    default:
      return state;
  }
}

const OnboardingUpload = ({ onComplete }: OnboardingUploadProps) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const completeTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const didCompleteRef = useRef(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;
  const [state, dispatch] = useReducer(uploadReducer, initialUploadState);
  const {
    isUploading,
    currentStep,
    uploadedFilename,
    uploadedTaskId,
    shouldCreateFilter,
    isCreatingFilter,
    ingestionReady,
    error,
    preview,
  } = state;

  const { runMode } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  const ingestPreviewEnabled = isIngestPreviewEnabled(runMode, {
    isCloudBrand,
  });
  const ingestPreviewEnabledRef = useRef(ingestPreviewEnabled);
  ingestPreviewEnabledRef.current = ingestPreviewEnabled;
  const previewOpenRef = useRef(preview.open);
  previewOpenRef.current = preview.open;
  const ingestionReadyRef = useRef(ingestionReady);
  ingestionReadyRef.current = ingestionReady;
  const isCreatingFilterRef = useRef(isCreatingFilter);
  isCreatingFilterRef.current = isCreatingFilter;

  const createFilterMutation = useCreateFilter();
  const updateOnboardingMutation = useUpdateOnboardingStateMutation();

  // Query tasks to track completion
  const { data: tasks } = useGetTasksQuery({
    enabled: currentStep !== null, // Only poll when upload has started
    refetchInterval: currentStep !== null ? 1000 : false, // Poll every 1 second during upload
  });

  const { refetch: refetchNudges } = useGetNudgesQuery(null);

  const cancelScheduledComplete = useCallback(() => {
    clearTimeout(completeTimeoutRef.current);
    completeTimeoutRef.current = undefined;
  }, []);

  // Schedule advancing to chat from the completion path itself (not a follow-up
  // effect watching ingestionReady). Delay while the review dialog is open.
  const scheduleComplete = useCallback(() => {
    if (didCompleteRef.current || completeTimeoutRef.current) return;
    if (ingestPreviewEnabledRef.current && previewOpenRef.current) return;

    const timeoutId = setTimeout(() => {
      didCompleteRef.current = true;
      completeTimeoutRef.current = undefined;
      onCompleteRef.current();
    }, 1000);
    completeTimeoutRef.current = timeoutId;
  }, []);

  // Monitor tasks and mark ingestion ready when file processing is done
  useEffect(() => {
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

      cancelScheduledComplete();
      didCompleteRef.current = false;
      dispatch({ type: "ingestion_failed", error: errorMessage });
      return;
    }

    // If task is completed or has processed files, prepare to finish the step
    if (!isTaskActive || (matchingTask.processed_files ?? 0) > 0) {
      // Create knowledge filter for uploaded document if requested
      // Guard against race condition: only create if not already creating
      if (shouldCreateFilter && uploadedFilename && !isCreatingFilter) {
        const filename = uploadedFilename;
        // Reset flags immediately (synchronously) to prevent duplicate creation
        dispatch({ type: "begin_create_filter", filename });

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
            }
          })
          .catch((filterError) => {
            console.error("Failed to create knowledge filter:", filterError);
          })
          .finally(() => {
            // Always mark ready — task-poll effect re-runs must not leave us stuck
            // with Done steps but ingestionReady never set.
            refetchNudges();
            dispatch({ type: "finish_create_filter" });
            scheduleComplete();
          });
      } else if (!isCreatingFilter && !ingestionReady) {
        refetchNudges();
        dispatch({ type: "mark_ingestion_ready" });
        scheduleComplete();
      }
    }
  }, [
    tasks,
    currentStep,
    refetchNudges,
    shouldCreateFilter,
    uploadedFilename,
    uploadedTaskId,
    createFilterMutation,
    isCreatingFilter,
    ingestionReady,
    updateOnboardingMutation.mutateAsync,
    cancelScheduledComplete,
    scheduleComplete,
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
    didCompleteRef.current = false;
    cancelScheduledComplete();
    // Onboarding always opens the review when the feature flag is on.
    dispatch({
      type: "start_upload",
      preview: ingestPreviewEnabled
        ? {
            open: true,
            taskIds: [],
            filename: file.name,
            files: [file],
          }
        : null,
    });
    try {
      dispatch({ type: "set_step", step: 0 });
      const result = await uploadFile(
        file,
        true,
        true,
        undefined,
        ingestPreviewEnabled,
      );

      let nextPreview: PreviewDialogState | null = null;
      if (result.taskId) {
        if (result.previewMode) {
          nextPreview = {
            open: true,
            taskIds: [result.taskId],
            filename: file.name,
            files: [file],
          };
        } else if (ingestPreviewEnabled) {
          nextPreview = EMPTY_PREVIEW;
        }
      }

      dispatch({
        type: "upload_succeeded",
        taskId: result.taskId ?? null,
        preview: nextPreview,
        filename:
          result.createFilter && result.filename ? result.filename : null,
        createFilter: Boolean(result.createFilter && result.filename),
      });

      // Move to processing step - task monitoring will handle completion
      setTimeout(() => {
        dispatch({ type: "set_step", step: 1 });
      }, 1500);
    } catch (uploadError) {
      const errorMessage =
        uploadError instanceof Error ? uploadError.message : "Upload failed";
      console.error("Upload failed", errorMessage);
      dispatch({ type: "upload_failed", error: errorMessage });

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
    } finally {
      dispatch({ type: "upload_finished" });
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
    } catch (prepareError) {
      console.error(
        "Unable to prepare file for upload",
        (prepareError as Error).message,
      );
    } finally {
      resetFileInput();
    }
  };

  return (
    <>
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
              setCurrentStep={(step) => dispatch({ type: "set_step", step })}
              isCompleted={false}
              steps={STEP_LIST}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <IngestReviewDialog
        open={preview.open}
        onOpenChange={(open) => {
          dispatch({
            type: "set_preview",
            preview: open ? { ...preview, open } : EMPTY_PREVIEW,
          });
          // Preview was holding completion — advance once the dialog closes.
          if (
            !open &&
            ingestionReadyRef.current &&
            !isCreatingFilterRef.current
          ) {
            previewOpenRef.current = false;
            scheduleComplete();
          }
        }}
        taskIds={preview.taskIds}
        previewFiles={preview.files}
        showAutoOpenFooter
      />
    </>
  );
};

export default OnboardingUpload;
