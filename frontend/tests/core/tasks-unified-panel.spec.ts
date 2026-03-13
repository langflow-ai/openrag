import { expect, type Page, type Route, test } from "@playwright/test";

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

const buildTask = (
  overrides: Partial<MockTask> & { task_id: string; status: MockTaskStatus },
): MockTask => {
  const now = new Date().toISOString();
  const { task_id, status, ...rest } = overrides;
  return {
    task_id,
    status,
    total_files: 2,
    processed_files: 0,
    successful_files: 0,
    failed_files: 0,
    running_files: 0,
    pending_files: 0,
    created_at: now,
    updated_at: now,
    files: {},
    ...rest,
  };
};

const wireTasksTransition = async (
  page: Page,
  before: MockTask[],
  after: MockTask[],
  switchAfterMs = 3000,
) => {
  let firstRequestMs: number | null = null;
  await page.route("**/api/tasks", async (route: Route) => {
    if (firstRequestMs === null) {
      firstRequestMs = Date.now();
    }
    const elapsedMs = Date.now() - firstRequestMs;
    const tasks = elapsedMs >= switchAfterMs ? after : before;

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tasks }),
    });
  });
};

const expandFirstFailureAccordion = async (page: Page) => {
  await page
    .getByRole("button", { name: /\d+\s*success,\s*\d+\s*failed/i })
    .first()
    .click();
};

test("completed task with failures keeps failure log in Tasks panel", async ({
  page,
}) => {
  const runningTask = buildTask({
    task_id: "task-12345678",
    status: "running",
    total_files: 2,
    processed_files: 1,
    successful_files: 1,
    running_files: 1,
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
  });

  const completedWithFailureTask = buildTask({
    task_id: "task-12345678",
    status: "completed",
    total_files: 2,
    processed_files: 2,
    successful_files: 1,
    failed_files: 1,
    running_files: 0,
    pending_files: 0,
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
  });
  await wireTasksTransition(page, [runningTask], [completedWithFailureTask]);

  await page.goto("/knowledge");

  // Wait for completion toast from task transition and open panel via "View".
  await expect(page.getByText("Task completed")).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("button", { name: "View", exact: true }).click();

  // Unified panel requirement (TDD): completed task with failed files
  // should preserve the detailed failure log content in the same Tasks panel.
  await expect(page.getByTestId("tasks-panel-title")).toBeVisible();
  await expandFirstFailureAccordion(page);
  await expect(page.getByText("Failure Log")).toBeVisible();
  await expect(
    page.getByText("Synthetic ingestion failure for test"),
  ).toBeVisible();
});

test("completed task with failures requires View click to open tasks panel", async ({
  page,
}) => {
  const runningTask = buildTask({
    task_id: "task-auto-open-completed",
    status: "running",
    total_files: 1,
    processed_files: 0,
    pending_files: 1,
    files: {
      "/tmp/doc-failed.pdf": {
        status: "running",
        filename: "doc-failed.pdf",
      },
    },
  });
  const completedWithFailureTask = buildTask({
    task_id: "task-auto-open-completed",
    status: "completed",
    total_files: 1,
    processed_files: 1,
    successful_files: 0,
    failed_files: 1,
    files: {
      "/tmp/doc-failed.pdf": {
        status: "failed",
        filename: "doc-failed.pdf",
        error: "Auto-open on partial success",
      },
    },
  });

  await wireTasksTransition(page, [runningTask], [completedWithFailureTask]);
  await page.goto("/knowledge");

  // No manual "View" click: completed-with-failures should NOT auto-open panel.
  await expect(page.getByText("Task completed")).toBeVisible({
    timeout: 15000,
  });

  await page.getByRole("button", { name: "View", exact: true }).click();
  await expect(page.getByTestId("tasks-panel-title")).toBeVisible();
  await expandFirstFailureAccordion(page);
  await expect(page.getByText("Failure Log")).toBeVisible();
  await expect(page.getByText("Auto-open on partial success")).toBeVisible();
});

test("new failed task auto-opens tasks panel", async ({ page }) => {
  const runningTask = buildTask({
    task_id: "task-auto-open-failed",
    status: "running",
    total_files: 1,
    processed_files: 0,
    pending_files: 1,
    files: {
      "/tmp/doc-failed.pdf": {
        status: "running",
        filename: "doc-failed.pdf",
      },
    },
  });
  const failedTask = buildTask({
    task_id: "task-auto-open-failed",
    status: "failed",
    total_files: 1,
    processed_files: 1,
    successful_files: 0,
    failed_files: 1,
    files: {
      "/tmp/doc-failed.pdf": {
        status: "failed",
        filename: "doc-failed.pdf",
        error: "Auto-open on failed task",
      },
    },
  });

  await wireTasksTransition(page, [runningTask], [failedTask]);
  await page.goto("/knowledge");

  await expect(page.getByTestId("tasks-panel-title")).toBeVisible({
    timeout: 15000,
  });
  await expandFirstFailureAccordion(page);
  await expect(page.getByText("Failure Log")).toBeVisible();
  await expect(page.getByText("Auto-open on failed task")).toBeVisible();
});
