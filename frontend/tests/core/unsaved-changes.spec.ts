import { expect, type Page, test } from "@playwright/test";
import { navigateToApp } from "../utils/navigation";

async function makeAgentSettingsDirty(page: Page) {
  await navigateToApp(page, "/settings/agent");
  const instructions = page.getByLabel("Agent Instructions");
  await expect(instructions).toBeVisible({ timeout: 60000 });
  await instructions.fill(`${await instructions.inputValue()} unsaved`);
  await page.waitForTimeout(1000);
}

test.describe("unsaved settings navigation", () => {
  test("guards the sidebar Settings link", async ({ page }) => {
    await makeAgentSettingsDirty(page);

    await page.getByRole("link", { name: "Settings", exact: true }).click();

    await expect(
      page.getByRole("heading", { name: "Unsaved changes" }),
    ).toBeVisible();
    await expect(page).toHaveURL(/\/settings\/agent$/);
    await page.getByRole("button", { name: "Stay" }).click();
    await expect(page).toHaveURL(/\/settings\/agent$/);
  });

  test("guards browser Back navigation", async ({ page }) => {
    await page.goto("/chat");
    await makeAgentSettingsDirty(page);

    await page.goBack({ waitUntil: "commit" });

    await expect(
      page.getByRole("heading", { name: "Unsaved changes" }),
    ).toBeVisible();
    await expect(page).toHaveURL(/\/settings\/agent$/);
    await page.getByRole("button", { name: "Stay" }).click();
  });

  test("does not cancel middle clicks on settings tabs", async ({ page }) => {
    await navigateToApp(page, "/settings/agent");
    const wasNotCancelled = await page
      .getByRole("tab", { name: "Ingestion" })
      .evaluate((tab) =>
        tab.dispatchEvent(
          new MouseEvent("click", {
            bubbles: true,
            button: 1,
            cancelable: true,
          }),
        ),
      );

    expect(wasNotCancelled).toBe(true);
    await expect(page).toHaveURL(/\/settings\/agent$/);
  });
});
