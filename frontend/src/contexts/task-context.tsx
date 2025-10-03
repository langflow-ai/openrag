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
  useGetTasksQuery,
} from "@/app/api/queries/useGetTasksQuery";
import { useAuth } from "@/contexts/auth-context";

// Task interface is now imported from useGetTasksQuery

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
}
interface TaskContextType {
  tasks: Task[];
  files: TaskFile[];
  addTask: (taskId: string) => void;
  addFiles: (files: Partial<TaskFile>[], taskId: string) => void;
  removeTask: (taskId: string) => void;
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
    onSuccess: () => {
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
    console.log(tasks, previousTasksRef.current);

    // Check for task status changes by comparing with previous tasks
    tasks.forEach((currentTask) => {
      const previousTask = previousTasksRef.current.find(
        (prev) => prev.task_id === currentTask.task_id,
      );

      // Only show toasts if we have previous data and status has changed
      if (((previousTask && previousTask.status !== currentTask.status) || (!previousTask && previousTasksRef.current.length !== 0))) {
        console.log("task status changed", currentTask.status);
        // Process files from failed task and add them to files list
        if (currentTask.files && typeof currentTask.files === "object") {
          console.log("processing files", currentTask.files);
          const taskFileEntries = Object.entries(currentTask.files);
          const now = new Date().toISOString();

          taskFileEntries.forEach(([filePath, fileInfo]) => {
            if (typeof fileInfo === "object" && fileInfo) {
              // Use the filename from backend if available, otherwise extract from path
              const fileName = (fileInfo as any).filename || filePath.split("/").pop() || filePath;
              const fileStatus = fileInfo.status as string;

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
                    typeof fileInfo.created_at === "string"
                      ? fileInfo.created_at
                      : now,
                  updated_at:
                    typeof fileInfo.updated_at === "string"
                      ? fileInfo.updated_at
                      : now,
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
          previousTask && previousTask.status !== "completed" &&
          currentTask.status === "completed"
        ) {
          // Task just completed - show success toast with file counts
          const successfulFiles = currentTask.successful_files || 0;
          const failedFiles = currentTask.failed_files || 0;

          let description = "";
          if (failedFiles > 0) {
            description = `${successfulFiles} file${successfulFiles !== 1 ? 's' : ''} uploaded successfully, ${failedFiles} file${failedFiles !== 1 ? 's' : ''} failed`;
          } else {
            description = `${successfulFiles} file${successfulFiles !== 1 ? 's' : ''} uploaded successfully`;
          }

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
          setTimeout(() => {
          refetchSearch();
          setFiles((prevFiles) =>
            prevFiles.filter((file) => file.task_id !== currentTask.task_id || file.status === "failed"),
            );
          }, 500);
        } else if (
          previousTask && previousTask.status !== "failed" &&
          previousTask.status !== "error" &&
          (currentTask.status === "failed" || currentTask.status === "error")
        ) {
          // Task just failed - show error toast
          toast.error("Task failed", {
            description: `Task ${currentTask.task_id} failed: ${
              currentTask.error || "Unknown error"
            }`,
          });
        }
      }
    });

    // Store current tasks as previous for next comparison
    previousTasksRef.current = tasks;
  }, [tasks, refetchSearch]);

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
    setFiles([]);
    await refetchTasks();
  }, [refetchTasks]);

  const removeTask = useCallback((_taskId: string) => {
    // This is now handled by React Query automatically
    // Tasks will be removed from the list when they're no longer returned by the API
  }, []);

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
    removeTask,
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
