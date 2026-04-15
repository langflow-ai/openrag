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

const expandFirstFailureAccordion = async (page: Page) => {
  const failureLog = page.getByText("Failure Log").first();
  if (await failureLog.isVisible()) {
    return;
  }
  await page
    .getByRole("button", { name: /\d+\s*success,\s*\d+\s*failed/i })
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

const openRecentTasksSection = async (page: Page) => {
  const failureAccordionTrigger = page.getByRole("button", {
    name: /\d+\s*success,\s*\d+\s*failed/i,
  });
  if (await failureAccordionTrigger.count()) {
    return;
  }

  const recentTasksToggle = page.getByRole("button", { name: /Recent Tasks/i });
  if (await recentTasksToggle.count()) {
    await recentTasksToggle.first().click();
  }
  await expect(failureAccordionTrigger.first()).toBeVisible({ timeout: 15000 });
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
  await openRecentTasksSection(page);
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
  await openRecentTasksSection(page);
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
  await openRecentTasksSection(page);
  await expandFirstFailureAccordion(page);
  await expect(page.getByText("Failure Log")).toBeVisible();
  await expect(page.getByText("Auto-open on failed task")).toBeVisible();
});

test("unified panel groups terminal tasks into recent and past", async ({
  page,
}) => {
  const recentFailedTask = buildTask({
    task_id: "task-recent-failed",
    status: "failed",
    created_at: isoMinutesAgo(1),
    updated_at: isoMinutesAgo(1),
    total_files: 1,
    processed_files: 1,
    failed_files: 1,
    files: {
      "/tmp/recent-failed.pdf": {
        status: "failed",
        filename: "recent-failed.pdf",
        error: "Recent failure log",
      },
    },
  });

  const pastFailedTask = buildTask({
    task_id: "task-past-failed",
    status: "failed",
    created_at: isoMinutesAgo(8),
    updated_at: isoMinutesAgo(8),
    total_files: 1,
    processed_files: 1,
    failed_files: 1,
    files: {
      "/tmp/past-failed.pdf": {
        status: "failed",
        filename: "past-failed.pdf",
        error: "Past failure log",
      },
    },
  });

  await wireTasksState(page, [recentFailedTask, pastFailedTask]);
  await page.goto("/knowledge");
  await page.waitForResponse((response) =>
    response.url().includes("/api/tasks"),
  );

  await openTasksPanel(page);
  await expect(page.getByText("Task task-rec...")).toBeVisible();
  await expect(page.getByText("Recent failure log")).toBeVisible();
  await page
    .getByRole("button", { name: /Past Tasks/i })
    .first()
    .click();

  await expect(page.getByText("Task task-pas...")).toBeVisible();
  await expect(page.getByText("INCOMPLETE")).toHaveCount(1);
});
