import { expect, test } from "@playwright/test";

test("has onboarding content", async ({ page }) => {
  // Go to the base URL (frontend)
  await page.goto("/");

  // Expect a title "to contain" a substring.
  await expect(page).toHaveTitle(/OpenRAG/);

  // Expect the onboarding content to be visible using the test id.
  await expect(page.getByTestId("onboarding-content")).toBeVisible({
    timeout: 30000,
  });
});
