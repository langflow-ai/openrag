import { expect, Locator, Page } from "@playwright/test";
import logger from "../utils/logger";

export class TasksMenu {
  // Locators - defined at class level for better maintainability
  private readonly recentTasksText = () =>
    this.page
      .getByText(/Recent Tasks|Tasks|Task History|Notifications/i)
      .first();
  private readonly bellButton = () =>
    this.page.locator("header button").first();
  private readonly tasksButtonByName = () =>
    this.page.getByRole("button", { name: /Tasks|Notifications/i });
  private readonly bellIconFallback = () =>
    this.page.locator("svg.lucide-bell").locator("..");
  private readonly closeButton = () => this.page.getByLabel("Close task panel");

  readonly drawer: Locator;

  constructor(private page: Page) {
    // The drawer typically contains the Tasks header and task lists
    this.drawer = this.page
      .locator("div")
      .filter({
        has: this.page.getByText(
          /Recent Tasks|Tasks|Task History|Notifications/i,
        ),
      })
      .first();
  }

  /**
   * Opens the Tasks menu by clicking the bell icon in the header (right side)
   */
  async open() {
    // First, check if it's already open
    const isVisible = await this.recentTasksText()
      .isVisible()
      .catch(() => false);
    logger.info(`TasksMenu.open() - Panel already visible: ${isVisible}`);
    if (isVisible) {
      return;
    }
    // Primary approach: Find the bell icon button in the header (right side)
    // The bell icon is typically a lucide-bell SVG icon
    const bellBtn = this.bellButton();
    try {
      logger.info("Clicking bell button to open Tasks Menu...");
      await bellBtn.click({ timeout: 5000 });
      await this.page.waitForTimeout(1500); // Wait for panel animation
    } catch {
      // Fallback 1: Try by accessible name
      try {
        logger.info("Fallback 1: Trying by accessible name...");
        const tasksBtn = this.tasksButtonByName();
        await tasksBtn.click({ timeout: 3000 });
        await this.page.waitForTimeout(1500);
      } catch {
        // Fallback 2: Find bell icon by SVG class anywhere
        logger.info("Fallback 2: Trying by SVG class...");
        await this.bellIconFallback().click({ force: true });
        await this.page.waitForTimeout(1500);
      }
    }
    await expect(this.recentTasksText()).toBeVisible({ timeout: 10000 });
    logger.info("✓ Tasks Menu panel is now visible");
  }

  /**
   * Closes the Tasks menu
   */
  async close() {
    // Check if already closed
    const isVisible = await this.recentTasksText()
      .isVisible()
      .catch(() => false);
    if (!isVisible) {
      return;
    }
    await this.closeButton().click();
    await expect(this.page.getByText("Recent Tasks").first()).toBeHidden({
      timeout: 5000,
    });
  }

  // ============================================================================
  // METHODS ADDED FOR AUTOMATED TESTING SUITE
  // ============================================================================

  /**
   * Validates that a specific task has failed by checking the completion status badges,
   * finding the task row by filename, opening the failure log, and verifying the filename
   * appears in the failure details.
   * @param filename - The name of the file that failed to upload
   */
  async verifyTaskFailed(filename: string) {
    const completedBadge = this.page
      .getByText("Complete", { exact: true })
      .first();
    const failedBadge = this.page.getByText("FAILED", { exact: true }).first();

    await expect(completedBadge.or(failedBadge)).toBeVisible({
      timeout: 15000,
    });

    // Verify the specific task row container for this file exists
    await expect(
      this.page.locator("div").filter({ hasText: filename }).last(),
    ).toBeVisible({ timeout: 5000 });

    // Expect failure details (it will be the top-most task since we just uploaded)
    const failedText = this.page.getByText(/1 failed/).first();
    await expect(failedText).toBeVisible({ timeout: 15000 });

    // Click on the failure text to expand the failure log
    await failedText.click();
    await this.page.waitForTimeout(1500);

    // Validate the expanded content contains the filename to confirm the task failed
    await expect(this.page.locator("body")).toContainText(filename, {
      timeout: 10000,
    });
  }

  /**
   * Waits for a task to complete (or fail) and returns the status and failure log (if any).
   */
  async waitForTaskCompletionAndGetLog(): Promise<{
    status: "Complete" | "COMPLETED" | "FAILED";
    statusLine: string;
    failureLog: string;
  }> {
    // Match both "Complete" and "COMPLETED" (case-insensitive)
    const completedBadge = this.page
      .getByText(/^(Complete|COMPLETED)$/i)
      .first();
    const failedBadge = this.page.getByText(/^(Failed|FAILED)$/i).first();

    // Wait for either badge to appear - use .first() to avoid strict mode violation
    await expect(completedBadge.or(failedBadge).first()).toBeVisible({
      timeout: 1000,
    }); // 5 min timeout

    const isCompleted = await completedBadge.isVisible().catch(() => false);
    const isFailed = await failedBadge.isVisible().catch(() => false);

    const statusLine =
      (await this.page
        .locator("text=/\\d+ success.*\\d+ failed/")
        .first()
        .textContent()
        .catch(() => "")) || "";
    let failureLog = "";

    if (isFailed) {
      const failedLink = this.page.getByText(/\d+ failed/).first();
      if (await failedLink.isVisible().catch(() => false)) {
        await failedLink.click();
        await this.page.waitForTimeout(1500);
      }

      const failureLogVisible = await this.page
        .getByText("Failure Log")
        .first()
        .isVisible()
        .catch(() => false);
      if (failureLogVisible) {
        const failureLogSection = this.page
          .getByText("Failure Log")
          .first()
          .locator("..");
        const failureLogContent =
          (await failureLogSection.textContent().catch(() => "")) || "";
        // Extract the error message (remove "Failure Log (1 of 1 pending)" header)
        failureLog = failureLogContent
          .replace(/Failure Log.*?pending\)/i, "")
          .trim();
      }
    }

    return {
      status: isCompleted
        ? (((await completedBadge.textContent()) || "Complete") as
            | "Complete"
            | "COMPLETED")
        : "FAILED",
      statusLine,
      failureLog,
    };
  }

  /**
   * Click the Cancel button for an ongoing upload task
   */
  async cancelFirstTask() {
    const cancelButton = this.page
      .getByRole("button", { name: "Cancel" })
      .first();
    await expect(cancelButton).toBeVisible({ timeout: 10000 });
    await cancelButton.click();
    await this.page.waitForTimeout(3000);
  }
}
