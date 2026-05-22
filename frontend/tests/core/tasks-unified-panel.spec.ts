import { expect, type Page, type Route, test } from "@playwright/test";
import { completeOnboarding } from "../utils/onboarding";

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await completeOnboarding(page, {
    llmProvider: "openai",
    embeddingProvider: "openai",
  });
});

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

const isoMinutesAgo = (minutes: number): string =>
  new Date(Date.now() - minutes * 60_000).toISOString();

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

const wireTasksState = async (page: Page, initialTasks: MockTask[]) => {
  let currentTasks = initialTasks;
  await page.route("**/api/tasks", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tasks: currentTasks }),
    });
  });

  return (nextTasks: MockTask[]) => {
    currentTasks = nextTasks;
  };
};

/** Matches accordion summary, e.g. "1 success · 2 failed". */
const FAILURE_SUMMARY_BUTTON = /\d+\s*success\s*[·,.]\s*\d+\s*failed/i;

const expandFirstFailureAccordion = async (
  page: Page,
  expectedError?: string,
) => {
  if (
    expectedError &&
    (await page.getByText(expectedError).first().isVisible())
  ) {
    return;
  }
  await page
    .getByRole("button", { name: FAILURE_SUMMARY_BUTTON })
    .first()
    .click();
};

const openTasksPanel = async (page: Page) => {
  const panelTitle = page.getByTestId("tasks-panel-title");
  try {
    await expect(panelTitle).toBeVisible({ timeout: 2000 });
    return;
  } catch {
    // Fall through to manual toggle open.
  }

  const toggle = page.getByTestId("task-menu-toggle");
  await toggle.click();
  try {
    await expect(panelTitle).toBeVisible({ timeout: 8000 });
    return;
  } catch {
    // If auto-open raced with our click and closed it, click once more.
    await toggle.click();
  }
  await expect(panelTitle).toBeVisible({ timeout: 15000 });
};

const openPastTasksSection = async (page: Page) => {
  const pastTasksToggle = page.getByRole("button", { name: /Past Tasks/i });
  await expect(pastTasksToggle.first()).toBeVisible({ timeout: 15000 });

  const failureSummary = page.getByRole("button", {
    name: FAILURE_SUMMARY_BUTTON,
  });
  if ((await failureSummary.count()) === 0) {
    await pastTasksToggle.first().click();
  }

  await expect(failureSummary.first()).toBeVisible({ timeout: 15000 });
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
  const setTasks = await wireTasksState(page, [runningTask]);

  await page.goto("/knowledge");
  await page.waitForResponse((response) =>
    response.url().includes("/api/tasks"),
  );
  setTasks([completedWithFailureTask]);
  await page.waitForResponse((response) =>
    response.url().includes("/api/tasks"),
  );
  await openTasksPanel(page);
  await openPastTasksSection(page);
  await expandFirstFailureAccordion(
    page,
    "Synthetic ingestion failure for test",
  );
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

  const setTasks = await wireTasksState(page, [runningTask]);
  await page.goto("/knowledge");
  await page.waitForResponse((response) =>
    response.url().includes("/api/tasks"),
  );
  setTasks([completedWithFailureTask]);
  await page.waitForResponse((response) =>
    response.url().includes("/api/tasks"),
  );
  await openTasksPanel(page);
  await openPastTasksSection(page);
  await expandFirstFailureAccordion(page, "Auto-open on partial success");
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

  const setTasks = await wireTasksState(page, [runningTask]);
  await page.goto("/knowledge");
  await page.waitForResponse((response) =>
    response.url().includes("/api/tasks"),
  );
  setTasks([failedTask]);
  await page.waitForResponse((response) =>
    response.url().includes("/api/tasks"),
  );
  await openTasksPanel(page);
  await openPastTasksSection(page);
  await expandFirstFailureAccordion(page, "Auto-open on failed task");
  await expect(page.getByText("Auto-open on failed task")).toBeVisible();
});

test("unified panel shows all completed tasks in a single past tasks section", async ({
  page,
}) => {
  const olderFailedTask = buildTask({
    task_id: "task-older-failed",
    status: "failed",
    created_at: isoMinutesAgo(8),
    updated_at: isoMinutesAgo(8),
    total_files: 1,
    processed_files: 1,
    failed_files: 1,
    files: {
      "/tmp/older-failed.pdf": {
        status: "failed",
        filename: "older-failed.pdf",
        error: "Older failure log",
      },
    },
  });

  const newerFailedTask = buildTask({
    task_id: "task-newer-failed",
    status: "failed",
    created_at: isoMinutesAgo(1),
    updated_at: isoMinutesAgo(1),
    total_files: 1,
    processed_files: 1,
    failed_files: 1,
    files: {
      "/tmp/newer-failed.pdf": {
        status: "failed",
        filename: "newer-failed.pdf",
        error: "Newer failure log",
      },
    },
  });

  await wireTasksState(page, [olderFailedTask, newerFailedTask]);
  await page.goto("/knowledge");
  await page.waitForResponse((response) =>
    response.url().includes("/api/tasks"),
  );

  await openTasksPanel(page);
  await expect(page.getByText("Task task-new...")).toBeVisible();
  await expect(page.getByText("Task task-old...")).toBeVisible();
  // Failure summaries stay collapsed by default; both tasks show the Failed pill.
  await expect(page.getByText("Failed", { exact: true })).toHaveCount(2);
});
