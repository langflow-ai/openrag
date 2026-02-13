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
import {
  type Task,
  type TaskFileEntry,
  useGetTasksQuery,
} from "@/app/api/queries/useGetTasksQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";

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
  refreshTasks: () => Promise<void>;
  cancelTask: (taskId: string) => Promise<void>;
  isPolling: boolean;
  isFetching: boolean;
  isMenuOpen: boolean;
  toggleMenu: () => void;
  isRecentTasksExpanded: boolean;
  setRecentTasksExpanded: (expanded: boolean) => void;
  // React Query states
  isLoading: boolean;
  error: Error | null;
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

export function TaskProvider({ children }: { children: React.ReactNode }) {
  const [files, setFiles] = useState<TaskFile[]>([]);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isRecentTasksExpanded, setIsRecentTasksExpanded] = useState(false);
  const previousTasksRef = useRef<Task[]>([]);
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
      queryClient.setQueryData(["tasks"], (oldTasks: Task[] | undefined) => {
        if (!oldTasks) return [];
        return oldTasks.filter((task) => task.task_id !== variables.taskId);
      });

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

  // Get settings to check if onboarding is active
  const { data: settings } = useGetSettingsQuery();

  // Helper function to check if onboarding is active
  const isOnboardingActive = useCallback(() => {
    const TOTAL_ONBOARDING_STEPS = 4;
    // Onboarding is active if current_step < 4
    return (
      settings?.onboarding?.current_step !== undefined &&
      settings.onboarding.current_step < TOTAL_ONBOARDING_STEPS
    );
  }, [settings?.onboarding?.current_step]);

  const refetchSearch = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ["search"],
      exact: false,
    });
  }, [queryClient]);

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

      // Check if task is in progress
      const isTaskInProgress =
        currentTask.status === "pending" ||
        currentTask.status === "running" ||
        currentTask.status === "processing";

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
                const existingFileIndex = prevFiles.findIndex(
                  (f) =>
                    f.source_url === filePath &&
                    f.task_id === currentTask.task_id,
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
                  // Update existing file
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
        if (
          shouldShowToast &&
          previousTask &&
          previousTask.status !== "completed" &&
          currentTask.status === "completed"
        ) {
          // Task just completed - show success toast with file counts
          const successfulFiles = currentTask.successful_files || 0;
          const failedFiles = currentTask.failed_files || 0;

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
          if (!isOnboardingActive()) {
            toast.success("Task completed", {
              description,
              action: {
                label: "View",
                onClick: () => {
                  setIsMenuOpen(true);
                  setIsRecentTasksExpanded(true);
                },
              },
            });
          }
          setTimeout(() => {
            // Only remove files from THIS specific task that completed
            setFiles((prevFiles) =>
              prevFiles.filter(
                (file) =>
                  file.task_id !== currentTask.task_id ||
                  file.status === "active" ||
                  file.status === "failed",
              ),
            );
            refetchSearch();
          }, 500);
        } else if (
          shouldShowToast &&
          previousTask &&
          previousTask.status !== "failed" &&
          previousTask.status !== "error" &&
          (currentTask.status === "failed" || currentTask.status === "error")
        ) {
          // Task just failed - show error toast
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
    refreshTasks,
    cancelTask,
    isPolling,
    isFetching,
    isMenuOpen,
    toggleMenu,
    isRecentTasksExpanded,
    setRecentTasksExpanded: setIsRecentTasksExpanded,
    isLoading,
    error,
  };

  return <TaskContext.Provider value={value}>{children}</TaskContext.Provider>;
}

export function useTask() {
  const context = useContext(TaskContext);
  if (context === undefined) {
    throw new Error("useTask must be used within a TaskProvider");
  }
  return context;
}
