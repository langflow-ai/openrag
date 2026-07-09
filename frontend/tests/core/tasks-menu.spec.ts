import { Page } from "@playwright/test";
import * as path from "path";
import { TasksMenu } from "../pages/TasksMenu";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToKnowledge } from "../utils/navigation";

/**
 * Tasks Menu Test Suite
 *
 * Tests the complete functionality of the Tasks Menu:
 * - Upload docling.pdf → Check Tasks Menu → Print result → Close
 * - Upload industry.csv → Check Tasks Menu → Print result → Close
 * All in a single test to maintain state
 */

async function openTasksMenuSafely(page: Page, tasksMenu: TasksMenu) {
  // Give the UI time to settle after any preceding action
  await page.waitForTimeout(1500);

  // Check if panel is already open — if so, no action needed
  const alreadyOpen =
    (await page
      .getByText("Recent Tasks")
      .first()
      .isVisible()
      .catch(() => false)) ||
    (await page
      .getByText("Tasks", { exact: true })
      .first()
      .isVisible()
      .catch(() => false));

  if (!alreadyOpen) {
    // Pre-click the bell icon directly from the spec as an extra attempt before
    // tasksMenu.open() runs its own strategies. This ensures the panel is triggered
    // even if the TasksMenu locators are slightly off for the current UI state.
    const bellSelectors = [
      // Most likely: Any button with SVG in header (bell icon is an SVG)
      "header button:has(svg)",
      // Try lucide-bell class
      "header button:has(svg.lucide-bell)",
      "button:has(svg.lucide-bell)",
      // Generic header buttons
      'header button[type="button"]',
      "header > div > button",
      // Position-based (bell is typically second from right, before profile)
      "header button:nth-last-child(2)",
      "header button:nth-last-child(3)",
      // Data attributes
      'button[data-testid*="bell"]',
      'button[data-testid*="notification"]',
      'button[data-testid*="task"]',
      // Fallback: any header button
      "header button",
    ];

    for (const selector of bellSelectors) {
      try {
        const btn = page.locator(selector).first();
        const visible = await btn
          .isVisible({ timeout: 2000 })
          .catch(() => false);
        if (visible) {
          await btn.click({ timeout: 3000 });
          await page.waitForTimeout(800);
          // Check if panel opened
          const opened =
            (await page
              .getByText("Recent Tasks")
              .first()
              .isVisible()
              .catch(() => false)) ||
            (await page
              .getByText("Tasks", { exact: true })
              .first()
              .isVisible()
              .catch(() => false));
          if (opened) break;
        }
      } catch {
        // try next selector
      }
    }
  }

  // Delegate to tasksMenu.open() — it will detect the panel is already open and return,
  // or retry its own click strategies if not yet open
  await tasksMenu.open();
}
test.describe("Tasks Menu Functionality @33219224 , @34581216", () => {
  test("Upload files and verify task status in Tasks Menu", async ({
    page,
    knowledge,
  }) => {
    test.setTimeout(300000); // 5 minutes

    // Add automatic login/navigation
    await navigateToKnowledge(page);

    const tasksMenu = new TasksMenu(page);

    // ========== UPLOAD 1: docling.pdf ==========
    const file1 = "docling.pdf";
    logger.info(`\n📋 Testing: ${file1}`);

    // Close Tasks Menu if it's open before upload
    const isTasksMenuOpen = await page
      .getByText("Recent Tasks")
      .first()
      .isVisible()
      .catch(() => false);
    if (isTasksMenuOpen) {
      await tasksMenu.close();
      await page.waitForTimeout(500);
    }

    // Upload docling.pdf and wait for completion
    const filePath1 = path.join(__dirname, "../test-data", file1);
    await knowledge.ingestFile(filePath1, true);
    logger.info(`   Upload completed for ${file1}`);

    // Now open Tasks Menu and check status
    await openTasksMenuSafely(page, tasksMenu);

    // Check task status for docling.pdf
    let result1 = await tasksMenu.waitForTaskCompletionAndGetLog();

    if (result1.status === "Complete" || result1.status === "COMPLETED") {
      logger.info(`✅ SUCCESS: ${file1} - ${result1.statusLine}`);
    } else {
      logger.info(`❌ FAILED: ${file1} - ${result1.statusLine}`);
      if (result1.failureLog) {
        logger.info(`\n   📋 Failure Log:`);
        const lines = result1.failureLog
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line);
        for (const line of lines) {
          logger.info(`   ${line}`);
        }
        logger.info("");
      }
    }

    // Close Tasks Menu
    await tasksMenu.close();
    await page.waitForTimeout(1000);

    // ========== UPLOAD 2: industry.csv ==========
    const file2 = "industry.csv";
    logger.info(`\n📋 Testing: ${file2}`);

    // Close Tasks Menu if it's open before upload
    const isTasksMenuOpen2 = await page
      .getByText("Recent Tasks")
      .first()
      .isVisible()
      .catch(() => false);
    if (isTasksMenuOpen2) {
      await tasksMenu.close();
      await page.waitForTimeout(500);
    }

    // Upload industry.csv and wait for completion
    const filePath2 = path.join(__dirname, "../test-data", file2);
    await knowledge.ingestFile(filePath2, true);
    logger.info(`   Upload completed for ${file2}`);

    // Now open Tasks Menu and check status
    await openTasksMenuSafely(page, tasksMenu);

    // Check task status for industry.csv
    let result2 = await tasksMenu.waitForTaskCompletionAndGetLog();

    if (result2.status === "Complete" || result2.status === "COMPLETED") {
      logger.info(`✅ SUCCESS: ${file2} - ${result2.statusLine}`);
    } else {
      logger.info(`❌ FAILED: ${file2} - ${result2.statusLine}`);
      if (result2.failureLog) {
        logger.info(`\n   📋 Failure Log:`);
        const lines = result2.failureLog
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line);
        for (const line of lines) {
          logger.info(`   ${line}`);
        }
        logger.info("");
      }
    }

    // Close Tasks Menu
    await tasksMenu.close();

    expect(
      result1.status === "Complete" || result1.status === "COMPLETED",
      result1.statusLine,
    ).toBe(true);
    expect(
      result2.status === "Complete" || result2.status === "COMPLETED",
      result2.statusLine,
    ).toBe(true);
  });

  //  test('Negative: Cancel file upload from Tasks Menu and verify failed status', async ({ page, knowledge }) => {
  //     test.setTimeout(120000);

  //     // Add automatic login/navigation
  //     await navigateToKnowledge(page);

  //     const tasksMenu = new TasksMenu(page);

  //     const file = 'heart.pdf';
  //     logger.info(`\n📋 Negative Test: ${file}`);

  //     // Close Tasks Menu if open
  //     const isTasksMenuOpen = await page.getByText('Recent Tasks').first().isVisible().catch(() => false);
  //     if (isTasksMenuOpen) {
  //       await tasksMenu.close();
  //       await page.waitForTimeout(500);
  //     }

  //     // Start file upload (non-blocking)
  //     const filePath = path.join(process.cwd(), 'test-data', file);
  //     await knowledge.ingestFileNonBlocking(filePath);

  //     // Open Tasks Menu and cancel upload
  //     await openTasksMenuSafely(page, tasksMenu);
  //     await page.waitForTimeout(1000);

  //     try {
  //       await tasksMenu.cancelFirstTask();

  //       // Verify FAILED status
  //       const failedBadge = page.getByText('FAILED').first();
  //       const isFailed = await failedBadge.isVisible().catch(() => false);

  //       if (isFailed) {
  //         logger.info(`✅ FAILED status verified after cancellation`);
  //         expect(isFailed).toBeTruthy();
  //       } else {
  //         const completedBadge = page.getByText('Complete').first();
  //         const isCompleted = await completedBadge.isVisible().catch(() => false);

  //         if (isCompleted) {
  //           logger.info(`ℹ️  Task completed before cancellation`);
  //         }
  //         expect(true).toBeTruthy();
  //       }

  //     } catch (error) {
  //       logger.info(`⚠️  Cancel button not found - task completed too quickly`);
  //       expect(true).toBeTruthy();
  //     }

  //     await tasksMenu.close();
  //   });
});
