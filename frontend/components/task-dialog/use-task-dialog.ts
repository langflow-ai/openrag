"use client";

import { useMemo, useState } from "react";
import { useGetTaskQuery } from "@/app/api/queries/useGetTaskQuery";
import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { useTask } from "@/contexts/task-context";
import {
  ALL_TASK_FILE_TYPES,
  ALL_TASK_STATUS_CATEGORIES,
  countTaskFilesByCategory,
  filterTaskFileEntries,
  getTaskFileEntries,
  getTaskFileTypes,
  sortTaskFileEntries,
  type TaskFileNameSort,
  TaskFileStatusCategory,
} from "@/lib/task-utils";

export function useTaskDialog(open: boolean, taskId: string) {
  const { tasks } = useTask();
  const { data: taskDetail } = useGetTaskQuery(taskId, { enabled: open });

  const [search, setSearch] = useState("");
  const [fileType, setFileType] = useState(ALL_TASK_FILE_TYPES);
  const [statusCategory, setStatusCategory] = useState(
    ALL_TASK_STATUS_CATEGORIES,
  );
  const [expandedPath, setExpandedPath] = useState<string | null>(null);
  const [nameSort, setNameSort] = useState<TaskFileNameSort>("asc");

  const task = useMemo<Task | undefined>(
    () => taskDetail ?? tasks.find((entry) => entry.task_id === taskId),
    [taskDetail, tasks, taskId],
  );

  const fileEntries = useMemo(
    () => (task ? getTaskFileEntries(task) : []),
    [task],
  );

  const fileTypes = useMemo(() => (task ? getTaskFileTypes(task) : []), [task]);

  const categoryCounts = useMemo(
    () => (task ? countTaskFilesByCategory(task) : null),
    [task],
  );

  const activeFileType =
    fileType === ALL_TASK_FILE_TYPES || fileTypes.includes(fileType)
      ? fileType
      : ALL_TASK_FILE_TYPES;

  const filteredEntries = useMemo(
    () =>
      filterTaskFileEntries(fileEntries, {
        search,
        fileType: activeFileType,
        statusCategory: statusCategory as TaskFileStatusCategory,
        task,
      }),
    [fileEntries, search, activeFileType, statusCategory, task],
  );

  const sortedEntries = useMemo(
    () => sortTaskFileEntries(filteredEntries, nameSort),
    [filteredEntries, nameSort],
  );

  const toggleNameSort = () => {
    setNameSort((current) => (current === "asc" ? "desc" : "asc"));
  };

  return {
    task,
    fileEntries,
    fileTypes,
    categoryCounts,
    sortedEntries,
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
