"use client";

import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  type RetryTaskResponse,
  useRetryTaskMutation,
} from "@/app/api/mutations/useRetryTaskMutation";
import { useGetTaskQuery } from "@/app/api/queries/useGetTaskQuery";
import { useTask } from "@/contexts/task-context";
import {
  ALL_TASK_FILE_TYPES,
  ALL_TASK_STATUS_CATEGORIES,
  countRetryIngestionFiles,
  countTaskFileEntriesByCategory,
  filterTaskFileEntries,
  getRetryableFileEntries,
  getRetryableFilePaths,
  getTaskFileEntries,
  getTaskFileTypes,
  isTaskInProgressStatus,
  sortTaskFileEntries,
  type TaskFileNameSort,
  TaskFileStatusCategory,
} from "@/lib/task-utils";

function showRetryResultToast(result: RetryTaskResponse) {
  if (result.skipped.length > 0) {
    const missingSources = result.skipped.filter(
      (entry) => entry.reason === "source_file_missing",
    ).length;
    if (missingSources > 0) {
      toast.warning("Some files could not be retried", {
        description: `${result.retried} file(s) queued. ${missingSources} need to be uploaded again.`,
      });
      return;
    }
  }

  if (result.retried > 0) {
    toast.success("Retry started", {
      description: `${result.retried} file(s) queued for ingestion`,
    });
    return;
  }

  toast.warning("No files were retried", {
    description: result.message ?? "Selected files could not be retried",
  });
}

export function useTaskDialog(open: boolean, taskId: string) {
  const { markTaskFilesProcessing, refreshTasks } = useTask();

  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(
    () => new Set(),
  );

  const [retryingTarget, setRetryingTarget] = useState<
    "all" | "selected" | string | null
  >(null);

  const retryMutation = useRetryTaskMutation();

  const {
    data: task,
    isLoading,
    isError,
    refetch: refetchTask,
  } = useGetTaskQuery(taskId, {
    enabled: open && !!taskId,
    refetchOnMount: "always",
    refetchInterval: (query) => {
      if (!open) {
        return false;
      }
      if (retryingTarget != null) {
        return 2000;
      }
      const data = query.state.data;
      if (!data) {
        return false;
      }
      if (isTaskInProgressStatus(data.status)) {
        return 2000;
      }
      return getTaskFileEntries(data).some(([, fileInfo]) => {
        const status = fileInfo.status ?? "pending";
        return (
          status === "pending" ||
          status === "running" ||
          status === "processing"
        );
      })
        ? 2000
        : false;
    },
  });

  const retryableCount = useMemo(
    () => (task ? countRetryIngestionFiles(task) : 0),
    [task],
  );

  const [search, setSearch] = useState("");
  const [fileType, setFileType] = useState(ALL_TASK_FILE_TYPES);
  const [statusCategory, setStatusCategory] = useState(
    ALL_TASK_STATUS_CATEGORIES,
  );
  const [expandedPath, setExpandedPath] = useState<string | null>(null);
  const [nameSort, setNameSort] = useState<TaskFileNameSort>("asc");

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (!open) {
      setSelectedPaths(new Set());
    }
  }

  const fileEntries = useMemo(
    () => (task ? getTaskFileEntries(task) : []),
    [task],
  );

  const fileTypes = useMemo(() => (task ? getTaskFileTypes(task) : []), [task]);

  const activeFileType =
    fileType === ALL_TASK_FILE_TYPES || fileTypes.includes(fileType)
      ? fileType
      : ALL_TASK_FILE_TYPES;

  const categoryCounts = useMemo(() => {
    if (!task) {
      return null;
    }
    const scopedEntries = filterTaskFileEntries(fileEntries, {
      search,
      fileType: activeFileType,
      statusCategory: ALL_TASK_STATUS_CATEGORIES,
    });
    return countTaskFileEntriesByCategory(scopedEntries);
  }, [task, fileEntries, search, activeFileType]);

  if (
    categoryCounts &&
    statusCategory !== ALL_TASK_STATUS_CATEGORIES &&
    (categoryCounts[statusCategory as TaskFileStatusCategory] ?? 0) === 0
  ) {
    setStatusCategory(ALL_TASK_STATUS_CATEGORIES);
  }

  const filteredEntries = useMemo(
    () =>
      filterTaskFileEntries(fileEntries, {
        search,
        fileType: activeFileType,
        statusCategory: statusCategory as TaskFileStatusCategory,
        task: task ?? undefined,
      }),
    [fileEntries, search, activeFileType, statusCategory, task],
  );

  const sortedEntries = useMemo(
    () => sortTaskFileEntries(filteredEntries, nameSort),
    [filteredEntries, nameSort],
  );

  const retryIngestionEntries = useMemo(
    () =>
      task ? sortTaskFileEntries(getRetryableFileEntries(task), nameSort) : [],
    [task, nameSort],
  );

  const retryIngestionPaths = useMemo(
    () => retryIngestionEntries.map(([filePath]) => filePath),
    [retryIngestionEntries],
  );

  const selectablePaths = useMemo(
    () => getRetryableFilePaths(sortedEntries),
    [sortedEntries],
  );

  const allRetryablePaths = useMemo(
    () => (task ? getRetryableFilePaths(getRetryableFileEntries(task)) : []),
    [task],
  );

  const selectedCount = useMemo(() => {
    let count = 0;
    for (const path of selectablePaths) {
      if (selectedPaths.has(path)) {
        count += 1;
      }
    }
    return count;
  }, [selectablePaths, selectedPaths]);

  const allSelectableSelected =
    selectablePaths.length > 0 && selectedCount === selectablePaths.length;

  const retryIngestionSelectedCount = useMemo(() => {
    let count = 0;
    for (const path of retryIngestionPaths) {
      if (selectedPaths.has(path)) {
        count += 1;
      }
    }
    return count;
  }, [retryIngestionPaths, selectedPaths]);

  const allRetryIngestionsSelected =
    retryIngestionPaths.length > 0 &&
    retryIngestionSelectedCount === retryIngestionPaths.length;

  const selectedRetryablePaths = useMemo(
    () => allRetryablePaths.filter((path) => selectedPaths.has(path)),
    [allRetryablePaths, selectedPaths],
  );

  const runRetry = useCallback(
    async (filePaths?: string[]) => {
      if (!taskId) {
        return;
      }
      if (!filePaths && retryableCount === 0) {
        return;
      }
      if (filePaths && filePaths.length === 0) {
        return;
      }

      const pathsToRetry =
        filePaths ??
        (task ? getRetryableFilePaths(getRetryableFileEntries(task)) : []);

      setRetryingTarget(
        filePaths
          ? filePaths.length === 1
            ? filePaths[0]
            : "selected"
          : "all",
      );

      if (pathsToRetry.length > 0) {
        markTaskFilesProcessing(taskId, pathsToRetry);
      }

      try {
        const result = await retryMutation.mutateAsync({
          taskId,
          ...(filePaths ? { filePaths } : {}),
        });
        await refetchTask();
        showRetryResultToast(result);
        if (result.retried > 0) {
          setSelectedPaths(new Set());
        }
      } catch (error) {
        await refreshTasks();
        toast.error("Retry failed", {
          description:
            error instanceof Error ? error.message : "Could not retry files",
        });
      } finally {
        setRetryingTarget(null);
      }
    },
    [
      task,
      taskId,
      retryableCount,
      retryMutation,
      refetchTask,
      markTaskFilesProcessing,
      refreshTasks,
    ],
  );

  const handleRetryAll = useCallback(() => runRetry(), [runRetry]);

  const handleRetrySelected = useCallback(
    () => runRetry(selectedRetryablePaths),
    [runRetry, selectedRetryablePaths],
  );

  const toggleSelectedPath = useCallback((filePath: string) => {
    setSelectedPaths((current) => {
      const next = new Set(current);
      if (next.has(filePath)) {
        next.delete(filePath);
      } else {
        next.add(filePath);
      }
      return next;
    });
  }, []);

  const toggleSelectAllVisible = useCallback(() => {
    setSelectedPaths((current) => {
      const visible = new Set(selectablePaths);
      const allSelected =
        selectablePaths.length > 0 &&
        selectablePaths.every((path) => current.has(path));

      if (allSelected) {
        const next = new Set(current);
        for (const path of visible) {
          next.delete(path);
        }
        return next;
      }

      const next = new Set(current);
      for (const path of visible) {
        next.add(path);
      }
      return next;
    });
  }, [selectablePaths]);

  const toggleSelectAllRetryIngestions = useCallback(() => {
    setSelectedPaths((current) => {
      const allSelected =
        retryIngestionPaths.length > 0 &&
        retryIngestionPaths.every((path) => current.has(path));

      if (allSelected) {
        const next = new Set(current);
        for (const path of retryIngestionPaths) {
          next.delete(path);
        }
        return next;
      }

      const next = new Set(current);
      for (const path of retryIngestionPaths) {
        next.add(path);
      }
      return next;
    });
  }, [retryIngestionPaths]);

  const toggleNameSort = () => {
    setNameSort((current) => (current === "asc" ? "desc" : "asc"));
  };

  return {
    task: task ?? undefined,
    isLoading,
    isError,
    retryableCount,
    selectedCount,
    selectedPaths,
    selectablePaths,
    allSelectableSelected,
    toggleSelectedPath,
    toggleSelectAllVisible,
    isRetrying: retryMutation.isPending,
    retryingTarget,
    handleRetryAll,
    handleRetrySelected,
    fileEntries,
    fileTypes,
    categoryCounts,
    sortedEntries,
    retryIngestionEntries,
    retryIngestionSelectedCount,
    allRetryIngestionsSelected,
    toggleSelectAllRetryIngestions,
    search,
    setSearch,
    fileType: activeFileType,
    setFileType,
    statusCategory,
    setStatusCategory,
    expandedPath,
    setExpandedPath,
    nameSort,
    toggleNameSort,
  };
}
