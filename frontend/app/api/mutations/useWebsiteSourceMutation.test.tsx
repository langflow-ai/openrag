import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";
import { useSyncWebsiteSourceMutation } from "./useWebsiteSourceMutation";

describe("useSyncWebsiteSourceMutation", () => {
  it("syncs a child page and automatically refreshes active task queries", async () => {
    let syncCalls = 0;
    let taskRequests = 0;
    server.use(
      http.post(
        "/api/connectors/url/sources/source-1/pages/page-1/sync",
        () => {
          syncCalls += 1;
          return HttpResponse.json({ task_id: "task-1" });
        },
      ),
      http.get("/api/tasks/enhanced", () => {
        taskRequests += 1;
        return HttpResponse.json({ tasks: [] });
      }),
    );

    const { result } = renderHook(
      () => {
        useGetTasksQuery();
        return useSyncWebsiteSourceMutation();
      },
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(taskRequests).toBeGreaterThan(0));
    const taskRequestsBeforeSync = taskRequests;

    await act(async () => {
      await result.current.mutateAsync({
        sourceId: "source-1",
        pageId: "page-1",
      });
    });

    expect(syncCalls).toBe(1);
    await waitFor(() =>
      expect(taskRequests).toBeGreaterThan(taskRequestsBeforeSync),
    );
  });
});
