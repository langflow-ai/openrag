import { X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useCreateFilter } from "@/app/api/mutations/useCreateFilter";
import { useGetNudgesQuery } from "@/app/api/queries/useGetNudgesQuery";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import { AnimatedProviderSteps } from "@/app/onboarding/_components/animated-provider-steps";
import { Button } from "@/components/ui/button";
import {
	ONBOARDING_UPLOAD_STEPS_KEY,
	ONBOARDING_USER_DOC_FILTER_ID_KEY,
} from "@/lib/constants";
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

	// Track which tasks we've already handled to prevent infinite loops
	const handledFailedTasksRef = useRef<Set<string>>(new Set());

	const createFilterMutation = useCreateFilter();

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

	// Monitor tasks and call onComplete when file processing is done
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

		// Skip if this task was already handled as a failed task (from a previous failed upload)
		// This prevents processing old failed tasks when a new upload starts
		if (handledFailedTasksRef.current.has(matchingTask.task_id)) {
			// Check if it's a failed task that we've already handled
			const hasFailedFile =
				matchingTask.files &&
				Object.values(matchingTask.files).some(
					(file) => file.status === "failed" || file.status === "error",
				);
			if (hasFailedFile) {
				// This is an old failed task that we've already handled, ignore it
				console.log(
					"Skipping already-handled failed task:",
					matchingTask.task_id,
				);
				return;
			}
			// If it's not a failed task, remove it from handled list (it might have succeeded on retry)
			handledFailedTasksRef.current.delete(matchingTask.task_id);
		}

		// Check if any file failed in the matching task
		const hasFailedFile = (() => {
			// Must have files object
			if (!matchingTask.files || typeof matchingTask.files !== "object") {
				return false;
			}

			const fileEntries = Object.values(matchingTask.files);

			// Must have at least one file
			if (fileEntries.length === 0) {
				return false;
			}

			// Check if any file has failed status
			return fileEntries.some(
				(file) => file.status === "failed" || file.status === "error",
			);
		})();

		// If any file failed, show error and jump back one step (like onboarding-card.tsx)
		// Only handle if we haven't already handled this task
		if (
			hasFailedFile &&
			!isCreatingFilter &&
			!handledFailedTasksRef.current.has(matchingTask.task_id)
		) {
			console.error("File failed in task, jumping back one step", matchingTask);

			// Mark this task as handled to prevent infinite loops
			handledFailedTasksRef.current.add(matchingTask.task_id);

			// Extract error messages from failed files
			const errorMessages: string[] = [];
			if (matchingTask.files) {
				Object.values(matchingTask.files).forEach((file) => {
					if (
						(file.status === "failed" || file.status === "error") &&
						file.error
					) {
						errorMessages.push(file.error);
					}
				});
			}

			// Also check task-level error
			if (matchingTask.error) {
				errorMessages.push(matchingTask.error);
			}

			// Use the first error message, or a generic message if no errors found
			const errorMessage =
				errorMessages.length > 0
					? errorMessages[0]
					: "Document failed to ingest. Please try again with a different file.";

			// Set error message and jump back one step
			setError(errorMessage);
			setCurrentStep(STEP_LIST.length);

			// Clear filter creation flags since ingestion failed
			setShouldCreateFilter(false);
			setUploadedFilename(null);

			// Jump back one step after 1 second (go back to upload step)
			setTimeout(() => {
				setCurrentStep(null);
			}, 1000);
			return;
		}

		// Check if the matching task is still active (pending, running, or processing)
		const isTaskActive =
			matchingTask.status === "pending" ||
			matchingTask.status === "running" ||
			matchingTask.status === "processing";

		// If task is completed successfully (no failures) and has processed files, complete the onboarding step
		if (
			(!isTaskActive || (matchingTask.processed_files ?? 0) > 0) &&
			!hasFailedFile
		) {
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
					.then((result) => {
						if (result.filter?.id && typeof window !== "undefined") {
							localStorage.setItem(
								ONBOARDING_USER_DOC_FILTER_ID_KEY,
								result.filter.id,
							);
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
            
						// Wait a bit before completing (after filter is created)
						setTimeout(() => {
							onComplete();
						}, 1000);
					});
			} else {
				// No filter to create, just complete

				// Wait a bit before completing
				setTimeout(() => {
					onComplete();
				}, 1000);
			}
		}
	}, [
		tasks,
		currentStep,
		onComplete,
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
		// Clear any previous error when user clicks to upload again
		setError(null);
		fileInputRef.current?.click();
	};

	const performUpload = async (file: File) => {
		setIsUploading(true);
		// Clear any previous error when starting a new upload
		setError(null);
		// Clear handled tasks ref to allow retry
		handledFailedTasksRef.current.clear();
		// Reset task ID to prevent matching old failed tasks
		setUploadedTaskId(null);
		// Clear filter creation flags
		setShouldCreateFilter(false);
		setUploadedFilename(null);

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
			setError(errorMessage);
			setShouldCreateFilter(false);
			setUploadedFilename(null);
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
					<div className="w-full flex flex-col gap-4">
						<AnimatePresence mode="wait">
							{error && (
								<motion.div
									key="error"
									initial={{ opacity: 1, y: 0, height: "auto" }}
									exit={{ opacity: 0, y: -10, height: 0 }}
								>
									<div className="pb-2 flex items-center gap-4">
										<X className="w-4 h-4 text-destructive shrink-0" />
										<span className="text-sm text-muted-foreground">
											{error}
										</span>
									</div>
								</motion.div>
							)}
						</AnimatePresence>
						<div>
							<Button
								size="sm"
								variant="outline"
								onClick={handleUploadClick}
								disabled={isUploading}
							>
								<div>{isUploading ? "Uploading..." : "Add a document"}</div>
							</Button>
						</div>
						<input
							ref={fileInputRef}
							type="file"
							onChange={handleFileChange}
							className="hidden"
							accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
						/>
					</div>
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
						storageKey={ONBOARDING_UPLOAD_STEPS_KEY}
						hasError={!!error}
					/>
				</motion.div>
			)}
		</AnimatePresence>
	);
};

export default OnboardingUpload;
