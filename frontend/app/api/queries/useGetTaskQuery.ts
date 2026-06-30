/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import type { Task } from "@/app/api/queries/useGetTasksQuery";

const TASK_DETAIL_QUERY_KEY = ["tasks", "detail"] as const;

export function taskDetailQueryKey(taskId: string) {
  return [...TASK_DETAIL_QUERY_KEY, taskId] as const;
}

export function useGetTaskQuery(
  taskId: string | null,
  options?: Omit<UseQueryOptions<Task | null>, "queryKey" | "queryFn">,
) {
  return useQuery({
    queryKey: taskId
      ? taskDetailQueryKey(taskId)
      : [...TASK_DETAIL_QUERY_KEY, "idle"],
    queryFn: async (): Promise<Task | null> => {
      if (!taskId) {
        return null;
      }
      const response = await fetch(
        `/api/tasks/${encodeURIComponent(taskId)}/enhanced`,
      );
      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        throw new Error("Failed to fetch task");
      }
      return response.json() as Promise<Task>;
    },
    ...options,
    enabled: options?.enabled ?? !!taskId,
  });
}
