"use client";

import { useQueryClient } from "@tanstack/react-query";
import type React from "react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";

export interface Task {
  task_id: string;
  status:
    | "pending"
    | "running"
    | "processing"
    | "completed"
    | "failed"
    | "error";
  total_files?: number;
  processed_files?: number;
  successful_files?: number;
  failed_files?: number;
  running_files?: number;
  pending_files?: number;
  created_at: string;
  updated_at: string;
  duration_seconds?: number;
  result?: Record<string, unknown>;
  error?: string;
  files?: Record<string, Record<string, unknown>>;
}

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
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

export function TaskProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [files, setFiles] = useState<TaskFile[]>([]);
  const [isPolling, setIsPolling] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const { isAuthenticated, isNoAuthMode } = useAuth();

  const queryClient = useQueryClient();

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

  const fetchTasks = useCallback(async () => {
    if (!isAuthenticated && !isNoAuthMode) return;

    setIsFetching(true);
    try {
      const response = await fetch("/api/tasks");
      if (response.ok) {
        const data = await response.json();
        const newTasks = data.tasks || [];

        // Update tasks and check for status changes in the same state update
        setTasks((prevTasks) => {
          // Check for newly completed tasks to show toasts
          if (prevTasks.length > 0) {
            newTasks.forEach((newTask: Task) => {
              const oldTask = prevTasks.find(
                (t) => t.task_id === newTask.task_id,
              );

              // Update or add files from task.files if available
              if (newTask.files && typeof newTask.files === "object") {
                const taskFileEntries = Object.entries(newTask.files);
                const now = new Date().toISOString();

                taskFileEntries.forEach(([filePath, fileInfo]) => {
                  if (typeof fileInfo === "object" && fileInfo) {
                    const fileName = filePath.split("/").pop() || filePath;
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
                          f.task_id === newTask.task_id,
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
                        task_id: newTask.task_id,
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
                oldTask &&
                oldTask.status !== "completed" &&
                newTask.status === "completed"
              ) {
                // Task just completed - show success toast
                toast.success("Task completed successfully", {
                  description: `Task ${newTask.task_id} has finished processing.`,
                  action: {
                    label: "View",
                    onClick: () => console.log("View task", newTask.task_id),
                  },
                });
                refetchSearch();
                // Dispatch knowledge updated event for all knowledge-related pages
                console.log(
                  "Task completed successfully, dispatching knowledgeUpdated event",
                );
                window.dispatchEvent(new CustomEvent("knowledgeUpdated"));

                // Remove files for this completed task from the files list
                setFiles((prevFiles) =>
                  prevFiles.filter((file) => file.task_id !== newTask.task_id),
                );
              } else if (
                oldTask &&
                oldTask.status !== "failed" &&
                oldTask.status !== "error" &&
                (newTask.status === "failed" || newTask.status === "error")
              ) {
                // Task just failed - show error toast
                toast.error("Task failed", {
                  description: `Task ${newTask.task_id} failed: ${
                    newTask.error || "Unknown error"
                  }`,
                });

                // Files will be updated to failed status by the file parsing logic above
              }
            });
          }

          return newTasks;
        });
      }
    } catch (error) {
      console.error("Failed to fetch tasks:", error);
    } finally {
      setIsFetching(false);
    }
  }, [isAuthenticated, isNoAuthMode, refetchSearch]); // Removed 'tasks' from dependencies to prevent infinite loop!

  const addTask = useCallback((taskId: string) => {
    // Immediately start aggressive polling for the new task
    let pollAttempts = 0;
    const maxPollAttempts = 30; // Poll for up to 30 seconds

    const aggressivePoll = async () => {
      try {
        const response = await fetch("/api/tasks");
        if (response.ok) {
          const data = await response.json();
          const newTasks = data.tasks || [];
          const foundTask = newTasks.find(
            (task: Task) => task.task_id === taskId,
          );

          if (foundTask) {
            // Task found! Update the tasks state
            setTasks((prevTasks) => {
              // Check if task is already in the list
              const exists = prevTasks.some((t) => t.task_id === taskId);
              if (!exists) {
                return [...prevTasks, foundTask];
              }
              // Update existing task
              return prevTasks.map((t) =>
                t.task_id === taskId ? foundTask : t,
              );
            });
            return; // Stop polling, we found it
          }
        }
      } catch (error) {
        console.error("Aggressive polling failed:", error);
      }

      pollAttempts++;
      if (pollAttempts < maxPollAttempts) {
        // Continue polling every 1 second for new tasks
        setTimeout(aggressivePoll, 1000);
      }
    };

    // Start aggressive polling after a short delay to allow backend to process
    setTimeout(aggressivePoll, 500);
  }, []);

  const refreshTasks = useCallback(async () => {
    await fetchTasks();
  }, [fetchTasks]);

  const removeTask = useCallback((taskId: string) => {
    setTasks((prev) => prev.filter((task) => task.task_id !== taskId));
  }, []);

  const cancelTask = useCallback(
    async (taskId: string) => {
      try {
        const response = await fetch(`/api/tasks/${taskId}/cancel`, {
          method: "POST",
        });

        if (response.ok) {
          // Immediately refresh tasks to show the updated status
          await fetchTasks();
          toast.success("Task cancelled", {
            description: `Task ${taskId.substring(0, 8)}... has been cancelled`,
          });
        } else {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || "Failed to cancel task");
        }
      } catch (error) {
        console.error("Failed to cancel task:", error);
        toast.error("Failed to cancel task", {
          description: error instanceof Error ? error.message : "Unknown error",
        });
      }
    },
    [fetchTasks],
  );

  const toggleMenu = useCallback(() => {
    setIsMenuOpen((prev) => !prev);
  }, []);

  // Periodic polling for task updates
  useEffect(() => {
    if (!isAuthenticated && !isNoAuthMode) return;

    setIsPolling(true);

    // Initial fetch
    fetchTasks();

    // Set up polling interval - every 3 seconds (more responsive for active tasks)
    const interval = setInterval(fetchTasks, 3000);

    return () => {
      clearInterval(interval);
      setIsPolling(false);
    };
  }, [isAuthenticated, isNoAuthMode, fetchTasks]);

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
