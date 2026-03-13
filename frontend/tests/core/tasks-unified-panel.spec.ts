import { expect, type Route, test } from "@playwright/test";

type MockTaskStatus =
  | "pending"
  | "running"
  | "processing"
  | "completed"
  | "failed"
  | "error";

interface MockTaskFileEntry {
  status: MockTaskStatus;
  filename: string;
  error?: string;
}

interface MockTask {
  task_id: string;
  status: MockTaskStatus;
  total_files: number;
  processed_files: number;
  successful_files: number;
  failed_files: number;
  running_files: number;
  pending_files: number;
  created_at: string;
  updated_at: string;
  files: Record<string, MockTaskFileEntry>;
}

test("completed task with failures keeps failure log in Tasks panel", async ({
  page,
}) => {
  const now = new Date().toISOString();
  let tasksRequestCount = 0;

  const runningTask: MockTask = {
    task_id: "task-12345678",
    status: "running",
    total_files: 2,
    processed_files: 1,
    successful_files: 1,
    failed_files: 0,
    running_files: 1,
    pending_files: 0,
    created_at: now,
    updated_at: now,
    files: {
      "/tmp/doc-success.pdf": {
        status: "completed",
        filename: "doc-success.pdf",
      },
      "/tmp/doc-failed.pdf": {
        status: "running",
        filename: "doc-failed.pdf",
      },
    },
  };

  const completedWithFailureTask: MockTask = {
    task_id: "task-12345678",
    status: "completed",
    total_files: 2,
    processed_files: 2,
    successful_files: 1,
    failed_files: 1,
    running_files: 0,
    pending_files: 0,
    created_at: now,
    updated_at: now,
    files: {
      "/tmp/doc-success.pdf": {
        status: "completed",
        filename: "doc-success.pdf",
      },
      "/tmp/doc-failed.pdf": {
        status: "failed",
        filename: "doc-failed.pdf",
        error: "Synthetic ingestion failure for test",
      },
    },
  };

  await page.route("**/api/tasks", async (route: Route) => {
    tasksRequestCount += 1;
    const tasks: MockTask[] =
      tasksRequestCount <= 1 ? [runningTask] : [completedWithFailureTask];

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tasks }),
    });
  });

  await page.goto("/knowledge");

  // Wait for completion toast from task transition and open panel via "View".
  await expect(page.getByText("Task completed")).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("button", { name: "View" }).click();

  // Unified panel requirement (TDD): completed task with failed files
  // should preserve the detailed failure log content in the same Tasks panel.
  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
  await expect(page.getByText("Failure Log")).toBeVisible();
  await expect(
    page.getByText("Synthetic ingestion failure for test"),
  ).toBeVisible();
});
