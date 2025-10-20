"use client";

import { useQueryClient } from "@tanstack/react-query";
import type React from "react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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

  // Derive files from tasks query data
  const files = useMemo(() => {
    const derivedFiles: TaskFile[] = [];
    const now = new Date().toISOString();

    tasks.forEach((task) => {
      if (task.files && typeof task.files === "object") {
        Object.entries(task.files).forEach(([filePath, fileInfo]) => {
          if (typeof fileInfo === "object" && fileInfo) {
            const fileInfoEntry = fileInfo as TaskFileEntry;
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
                typeof task.error === "string" &&
                task.error.trim().length > 0
              ) {
                return task.error.trim();
              }
              return undefined;
            })();

            // Detect connector type based on file path
            let connectorType = "local";
            if (filePath.includes("/") && !filePath.startsWith("/")) {
              connectorType = "s3";
            }

            derivedFiles.push({
              filename: fileName,
              mimetype: "",
              source_url: filePath,
              size: 0,
              connector_type: connectorType,
              status: mappedStatus,
              task_id: task.task_id,
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
            });
          }
        });
      }
    });

    return derivedFiles;
  }, [tasks]);

  // Handle task status changes for notifications
  useEffect(() => {
    if (tasks.length === 0) {
      previousTasksRef.current = tasks;
      return;
    }

    // Check for task status changes by comparing with previous tasks
    tasks.forEach((currentTask) => {
      const previousTask = previousTasksRef.current.find(
        (prev) => prev.task_id === currentTask.task_id
      );

      // Only show toasts if we have previous data and status has changed
      if (
        (previousTask && previousTask.status !== currentTask.status) ||
        (!previousTask && previousTasksRef.current.length !== 0)
      ) {
        if (
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
          queryClient.invalidateQueries({
            queryKey: ["search"],
            exact: false,
          });
        } else if (
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
        }
      }
    });

    // Store current tasks as previous for next comparison
    previousTasksRef.current = tasks;
  }, [tasks, queryClient]);

  const addTask = useCallback(
    (_taskId: string) => {
      // React Query will automatically handle polling when tasks are active
      // Just trigger a refetch to get the latest data
      setTimeout(() => {
        refetchTasks();
      }, 500);
    },
    [refetchTasks]
  );

  const refreshTasks = useCallback(async () => {
    await refetchTasks();
  }, [refetchTasks]);

  const cancelTask = useCallback(
    async (taskId: string) => {
      cancelTaskMutation.mutate({ taskId });
    },
    [cancelTaskMutation]
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
        task.status === "processing"
    );

  const value: TaskContextType = {
    tasks,
    files,
    addTask,
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
