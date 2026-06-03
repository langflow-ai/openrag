"use client";

import { useQueryClient } from "@tanstack/react-query";
import type React from "react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { useCancelTaskMutation } from "@/app/api/mutations/useCancelTaskMutation";
import type { SearchResult } from "@/app/api/queries/useGetSearchQuery";
import {
  TASKS_QUERY_KEY,
  type Task,
  type TaskFileEntry,
  useGetTasksQuery,
} from "@/app/api/queries/useGetTasksQuery";
import type { ListFilesResponse } from "@/app/api/queries/useListFiles";
import TaskDialog from "@/components/task-dialog";
import { useAuth } from "@/contexts/auth-context";
import { useOnboardingState } from "@/hooks/use-onboarding-state";
import { trackProcessFailure, trackProcessSuccess } from "@/lib/analytics";
import { getKnowledgeFileIdentity } from "@/lib/knowledge-table-state";
import {
  didTaskReachCompleted,
  finalizeProcessingOverlaysForEnhancedTask,
  findTaskFileOverlayIndex,
  getEnhancedListDisappearedFilePaths,
  getFailedFileCount,
  getSuccessfulFileCount,
  hasFailedFileEntries,
  isTaskInProgressStatus,
  isTerminalFailedTask,
} from "@/lib/task-utils";

// Task interface is now imported from useGetTasksQuery
export type { Task };

export interface TaskFile {
  filename: string;
  mimetype: string;
  source_url: string;
  size: number;
  connector_type: string;
  status: "active" | "failed" | "processing";
  task_id: string;
  created_at: string;
  updated_at: string;
  error?: string;
  embedding_model?: string;
  embedding_dimensions?: number;
}
interface TaskContextType {
  tasks: Task[];
  files: TaskFile[];
  addTask: (taskId: string) => void;
  addFiles: (files: Partial<TaskFile>[], taskId: string) => void;
  /** Mark knowledge-table overlays as processing when a retry starts. */
  markTaskFilesProcessing: (taskId: string, sourceUrls: string[]) => void;
  refreshTasks: () => Promise<void>;
  cancelTask: (taskId: string) => Promise<void>;
  isPolling: boolean;
  isFetching: boolean;
  isMenuOpen: boolean;
  openMenu: () => void;
  toggleMenu: () => void;
  closeMenu: () => void;
  isRecentTasksExpanded: boolean;
  setRecentTasksExpanded: (expanded: boolean) => void;
  selectedTaskId: string | null;
  setSelectedTaskId: (taskId: string | null) => void;
  selectedTaskTrigger: number;
  selectTask: (taskId: string | null) => void;
  isTaskDialogOpen: boolean;
  taskDialogTaskId: string | null;
  openTaskDialog: (taskId: string) => void;
  closeTaskDialog: () => void;
  // React Query states
  isLoading: boolean;
  error: Error | null;
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

export function TaskProvider({ children }: { children: React.ReactNode }) {
  const [files, setFiles] = useState<TaskFile[]>([]);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isRecentTasksExpanded, setIsRecentTasksExpanded] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedTaskTrigger, setSelectedTaskTrigger] = useState(0);
  const [taskDialogTaskId, setTaskDialogTaskId] = useState<string | null>(null);
  const [isTaskDialogOpen, setIsTaskDialogOpen] = useState(false);
  const previousTasksRef = useRef<Task[]>([]);
  const openTaskDialog = useCallback((taskId: string) => {
    setTaskDialogTaskId(taskId);
    setIsTaskDialogOpen(true);
  }, []);
  const closeTaskDialog = useCallback(() => {
    setIsTaskDialogOpen(false);
    setTaskDialogTaskId(null);
  }, []);
  const selectTask = useCallback((taskId: string | null) => {
    setSelectedTaskId(taskId);
    if (taskId) {
      setSelectedTaskTrigger((prev) => prev + 1);
    }
  }, []);

  const { isAuthenticated, isNoAuthMode } = useAuth();

  const queryClient = useQueryClient();

  // Use React Query hooks
  const {
    data: tasks = [],
    isLoading,
    error,
    refetch: refetchTasks,
    isFetching,
  } = useGetTasksQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const cancelTaskMutation = useCancelTaskMutation({
    onSuccess: (_data, variables) => {
      // Immediately remove from React Query cache
      queryClient.setQueryData(
        [...TASKS_QUERY_KEY],
        (oldTasks: Task[] | undefined) => {
          if (!oldTasks) return [];
          return oldTasks.filter((task) => task.task_id !== variables.taskId);
        },
      );

      // Update file to display as cancelled
      setFiles((prevFiles) =>
        prevFiles.map((file) => {
          if (file.task_id === variables.taskId) {
            return { ...file, status: "failed" };
          }
          return file;
        }),
      );

      toast.success("Task cancelled", {
        description: "Task has been cancelled successfully",
      });
    },
    onError: (error) => {
      toast.error("Failed to cancel task", {
        description: error.message,
      });
    },
  });

  const { isOnboardingActive } = useOnboardingState();

  const refetchSearch = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ["search"],
      exact: false,
    });
    queryClient.invalidateQueries({
      queryKey: ["listFiles"],
      exact: false,
    });
  }, [queryClient]);

  const markTaskFilesProcessing = useCallback(
    (taskId: string, sourceUrls: string[]) => {
      const paths = new Set(sourceUrls);
      if (paths.size === 0) {
        return;
      }
      const now = new Date().toISOString();
      setFiles((prevFiles) => {
        let changed = false;
        const updated = prevFiles.map((file) => {
          if (file.task_id !== taskId || !paths.has(file.source_url)) {
            return file;
          }
          changed = true;
          return {
            ...file,
            status: "processing" as const,
            error: undefined,
            updated_at: now,
          };
        });
        return changed ? updated : prevFiles;
      });
    },
    [],
  );

  const addFiles = useCallback(
    (newFiles: Partial<TaskFile>[], taskId: string) => {
      const now = new Date().toISOString();
      const filesToAdd: TaskFile[] = newFiles.map((file) => ({
        filename: file.filename || "",
        mimetype: file.mimetype || "",
        source_url: file.source_url || "",
        size: file.size || 0,
        connector_type: file.connector_type || "local",
        status: "processing",
        task_id: taskId,
        created_at: now,
        updated_at: now,
        error: file.error,
        embedding_model: file.embedding_model,
        embedding_dimensions: file.embedding_dimensions,
      }));

      setFiles((prevFiles) => [...prevFiles, ...filesToAdd]);
    },
    [],
  );

  // Handle task status changes and file updates
  useEffect(() => {
    if (tasks.length === 0) {
      // Store current tasks as previous for next comparison
      previousTasksRef.current = tasks;
      return;
    }

    // Check for task status changes by comparing with previous tasks
    tasks.forEach((currentTask) => {
      const previousTask = previousTasksRef.current.find(
        (prev) => prev.task_id === currentTask.task_id,
      );

      const isTaskInProgress = isTaskInProgressStatus(currentTask.status);

      // On initial load, previousTasksRef is empty, so we need to process all in-progress tasks
      const isInitialLoad = previousTasksRef.current.length === 0;

      // Process files if:
      // 1. Task is in progress (always process to keep files list updated)
      // 2. Status has changed
      // 3. New task appeared (not on initial load)
      const shouldProcessFiles =
        isTaskInProgress ||
        (previousTask && previousTask.status !== currentTask.status) ||
        (!previousTask && !isInitialLoad);

      // Only show toasts if we have previous data and status has changed
      const shouldShowToast =
        previousTask && previousTask.status !== currentTask.status;

      if (shouldProcessFiles) {
        // Process files from task and add them to files list
        if (currentTask.files && typeof currentTask.files === "object") {
          const taskFileEntries = Object.entries(currentTask.files);
          const now = new Date().toISOString();

          taskFileEntries.forEach(([filePath, fileInfo]) => {
            if (typeof fileInfo === "object" && fileInfo) {
              const fileInfoEntry = fileInfo as TaskFileEntry;
              // Use the filename from backend if available, otherwise extract from path
              const fileName =
                fileInfoEntry.filename || filePath.split("/").pop() || filePath;
              const fileStatus = fileInfoEntry.status ?? "processing";

              // Map backend file status to our TaskFile status
              let mappedStatus: TaskFile["status"];
              switch (fileStatus) {
                case "pending":
                case "running":
                  mappedStatus = "processing";
                  break;
                case "completed":
                  mappedStatus = "active";
                  break;
                case "failed":
                  mappedStatus = "failed";
                  break;
                default:
                  mappedStatus = "processing";
              }

              const fileError = (() => {
                if (
                  typeof fileInfoEntry.error === "string" &&
                  fileInfoEntry.error.trim().length > 0
                ) {
                  return fileInfoEntry.error.trim();
                }
                if (
                  mappedStatus === "failed" &&
                  typeof currentTask.error === "string" &&
                  currentTask.error.trim().length > 0
                ) {
                  return currentTask.error.trim();
                }
                return undefined;
              })();

              setFiles((prevFiles) => {
                const existingFileIndex = findTaskFileOverlayIndex(
                  prevFiles,
                  currentTask.task_id,
                  filePath,
                  fileName,
                );

                // Detect connector type based on file path or other indicators
                let connectorType = "local";
                if (filePath.includes("/") && !filePath.startsWith("/")) {
                  // Likely S3 key format (bucket/path/file.ext)
                  connectorType = "s3";
                }

                const fileEntry: TaskFile = {
                  filename: fileName,
                  mimetype: "", // We don't have this info from the task
                  source_url: filePath,
                  size: 0, // We don't have this info from the task
                  connector_type: connectorType,
                  status: mappedStatus,
                  task_id: currentTask.task_id,
                  created_at:
                    typeof fileInfoEntry.created_at === "string"
                      ? fileInfoEntry.created_at
                      : now,
                  updated_at:
                    typeof fileInfoEntry.updated_at === "string"
                      ? fileInfoEntry.updated_at
                      : now,
                  error: fileError,
                  embedding_model:
                    typeof fileInfoEntry.embedding_model === "string"
                      ? fileInfoEntry.embedding_model
                      : undefined,
                  embedding_dimensions:
                    typeof fileInfoEntry.embedding_dimensions === "number"
                      ? fileInfoEntry.embedding_dimensions
                      : undefined,
                };

                if (existingFileIndex >= 0) {
                  // Update by file identity so newer task attempts replace older
                  // failed/success overlays for the same file.
                  const updatedFiles = [...prevFiles];
                  updatedFiles[existingFileIndex] = fileEntry;
                  return updatedFiles;
                } else {
                  // Add new file
                  return [...prevFiles, fileEntry];
                }
              });
            }
          });
        }

        if (previousTask?.files) {
          const disappearedFilePaths = getEnhancedListDisappearedFilePaths(
            currentTask,
            previousTask,
          );
          const taskJustCompleted = didTaskReachCompleted(
            previousTask,
            currentTask,
          );
          const shouldFinalizeDisappeared =
            disappearedFilePaths.length > 0 &&
            (isTaskInProgress || taskJustCompleted);
          const shouldFinalizeAllProcessing = taskJustCompleted;

          if (shouldFinalizeDisappeared || shouldFinalizeAllProcessing) {
            setFiles((prevFiles) =>
              finalizeProcessingOverlaysForEnhancedTask(
                prevFiles,
                currentTask,
                shouldFinalizeAllProcessing ? undefined : disappearedFilePaths,
              ),
            );
            refetchSearch();
          }
        }
        if (
          shouldShowToast &&
          previousTask &&
          previousTask.status !== "completed" &&
          currentTask.status === "completed"
        ) {
          const successfulFiles = getSuccessfulFileCount(currentTask);
          const failedFiles = getFailedFileCount(currentTask);
          const isTotalFailure = failedFiles > 0 && successfulFiles === 0;

          if (isTotalFailure) {
            trackProcessFailure({
              processType: "Ingestion",
              process: "Document Upload",
              category: "Knowledge",
              task_id: currentTask.task_id,
              total_files: currentTask.total_files,
              failed_files: failedFiles,
              duration_seconds: currentTask.duration_seconds,
            });
          } else {
            trackProcessSuccess({
              processType: "Ingestion",
              process: "Document Upload",
              category: "Knowledge",
              task_id: currentTask.task_id,
              total_files: currentTask.total_files,
              successful_files: successfulFiles,
              failed_files: failedFiles,
              duration_seconds: currentTask.duration_seconds,
            });
          }

          let description = "";
          if (failedFiles > 0) {
            description = `${successfulFiles} file${
              successfulFiles !== 1 ? "s" : ""
            } uploaded successfully, ${failedFiles} file${
              failedFiles !== 1 ? "s" : ""
            } failed`;
          } else {
            description = `${successfulFiles} file${
              successfulFiles !== 1 ? "s" : ""
            } uploaded successfully`;
          }
          if (!isOnboardingActive) {
            const toastAction = {
              label: "View",
              onClick: () => {
                selectTask(currentTask.task_id);
                setIsMenuOpen(true);
                setIsRecentTasksExpanded(true);
              },
            };
            if (isTotalFailure) {
              toast.error("Task failed", {
                description: `${failedFiles} file${
                  failedFiles !== 1 ? "s" : ""
                } failed`,
                action: toastAction,
              });
            } else {
              toast.success("Task completed", {
                description,
                action: toastAction,
              });
            }
          }

          const completedHasFailures = hasFailedFileEntries(currentTask);

          async function refetchKnowledgeAfterTaskCompletion() {
            // Refetch before dropping overlays (wildcard uses listFiles, not only search).
            try {
              await Promise.all([
                queryClient.refetchQueries({
                  queryKey: ["search"],
                  exact: false,
                }),
                queryClient.refetchQueries({
                  queryKey: ["listFiles"],
                  exact: false,
                }),
              ]);
            } catch (e) {
              console.error(
                "Knowledge refetch after task completion failed",
                e,
              );
            } finally {
              const indexedIdentities = new Set<string>();
              const indexedFilenames = new Set<string>();
              for (const [
                ,
                data,
              ] of queryClient.getQueriesData<ListFilesResponse>({
                queryKey: ["listFiles"],
              })) {
                for (const indexed of data?.files ?? []) {
                  indexedIdentities.add(getKnowledgeFileIdentity(indexed));
                  if (indexed.filename?.trim()) {
                    indexedFilenames.add(indexed.filename.trim());
                  }
                }
              }
              for (const [, data] of queryClient.getQueriesData<SearchResult>({
                queryKey: ["search"],
              })) {
                for (const indexed of data?.files ?? []) {
                  indexedIdentities.add(getKnowledgeFileIdentity(indexed));
                  if (indexed.filename?.trim()) {
                    indexedFilenames.add(indexed.filename.trim());
                  }
                }
              }

              setFiles((prevFiles) =>
                prevFiles.filter((file) => {
                  if (file.task_id !== currentTask.task_id) {
                    return true;
                  }
                  if (file.status === "failed") {
                    return completedHasFailures;
                  }
                  if (file.status === "processing") {
                    return false;
                  }
                  if (file.status === "active") {
                    const identity = getKnowledgeFileIdentity({
                      filename: file.filename,
                      source_url: file.source_url,
                    });
                    if (identity && indexedIdentities.has(identity)) {
                      return false;
                    }
                    const sourceUrl = file.source_url?.trim();
                    if (!sourceUrl || !identity) {
                      const filename = file.filename?.trim();
                      if (filename && indexedFilenames.has(filename)) {
                        return false;
                      }
                    }
                    return true;
                  }
                  return false;
                }),
              );
            }
          }
          void refetchKnowledgeAfterTaskCompletion();
        } else if (
          shouldShowToast &&
          previousTask &&
          !isTerminalFailedTask(previousTask) &&
          isTerminalFailedTask(currentTask)
        ) {
          if (!isOnboardingActive) {
            selectTask(currentTask.task_id);
            setIsMenuOpen(true);
            setIsRecentTasksExpanded(true);
          }
          // Task just failed - show error toast
          trackProcessFailure({
            processType: "Ingestion",
            process: "Document Upload",
            category: "Knowledge",
            task_id: currentTask.task_id,
            total_files: currentTask.total_files,
            failed_files: currentTask.failed_files,
            duration_seconds: currentTask.duration_seconds,
            resultValue: currentTask.error,
          });
          toast.error("Task failed", {
            description: `Task ${currentTask.task_id} failed: ${
              currentTask.error || "Unknown error"
            }`,
          });

          // Set chat error flag to trigger test_completion=true on health checks
          // Only for ingestion-related tasks (tasks with files are ingestion tasks)
          if (currentTask.files && Object.keys(currentTask.files).length > 0) {
            // Dispatch event that chat context can listen to
            // This avoids circular dependency issues
            if (typeof window !== "undefined") {
              window.dispatchEvent(
                new CustomEvent("ingestionFailed", {
                  detail: { taskId: currentTask.task_id },
                }),
              );
            }
          }
        }
      }
    });

    // Store current tasks as previous for next comparison
    previousTasksRef.current = tasks;
  }, [tasks, refetchSearch, isOnboardingActive]);

  const addTask = useCallback(
    (_taskId: string) => {
      // React Query will automatically handle polling when tasks are active
      // Just trigger a refetch to get the latest data
      setTimeout(() => {
        refetchTasks();
      }, 500);
    },
    [refetchTasks],
  );

  const refreshTasks = useCallback(async () => {
    setFiles((prevFiles) =>
      prevFiles.filter(
        (file) => file.status !== "active" && file.status !== "failed",
      ),
    );
    await refetchTasks();
  }, [refetchTasks]);

  const cancelTask = useCallback(
    async (taskId: string) => {
      cancelTaskMutation.mutate({ taskId });
    },
    [cancelTaskMutation],
  );

  const toggleMenu = useCallback(() => {
    setIsMenuOpen((prev) => !prev);
  }, []);

  const openMenu = useCallback(() => {
    setIsMenuOpen(true);
  }, []);

  const closeMenu = useCallback(() => {
    setIsMenuOpen(false);
    setSelectedTaskId(null);
  }, []);

  // Determine if we're polling based on React Query's refetch interval
  const isPolling =
    isFetching &&
    tasks.some(
      (task) =>
        task.status === "pending" ||
        task.status === "running" ||
        task.status === "processing",
    );

  const value: TaskContextType = {
    tasks,
    files,
    addTask,
    addFiles,
    markTaskFilesProcessing,
    refreshTasks,
    cancelTask,
    isPolling,
    isFetching,
    isMenuOpen,
    openMenu,
    toggleMenu,
    closeMenu,
    isRecentTasksExpanded,
    setRecentTasksExpanded: setIsRecentTasksExpanded,
    selectedTaskId,
    setSelectedTaskId,
    selectedTaskTrigger,
    selectTask,
    isTaskDialogOpen,
    taskDialogTaskId,
    openTaskDialog,
    closeTaskDialog,
    isLoading,
    error,
  };

  return (
    <TaskContext.Provider value={value}>
      {children}
      {taskDialogTaskId ? (
        <TaskDialog
          open={isTaskDialogOpen}
          onOpenChange={(open) => {
            setIsTaskDialogOpen(open);
            if (!open) {
              setTaskDialogTaskId(null);
            }
          }}
          task_id={taskDialogTaskId}
          onClose={closeTaskDialog}
        />
      ) : null}
    </TaskContext.Provider>
  );
}

export function useTask() {
  const context = useContext(TaskContext);
  if (context === undefined) {
    throw new Error("useTask must be used within a TaskProvider");
  }
  return context;
}
