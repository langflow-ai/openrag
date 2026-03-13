import { expect, test } from "@playwright/test";

test("has onboarding content", async ({ page }) => {
  // Go to the base URL (frontend)
  await page.goto("/");

  // Expect a title "to contain" a substring.
  await expect(page).toHaveTitle(/OpenRAG/);

  // Depending on app state, users can land on onboarding or directly on chat.
  const onboardingContent = page.getByTestId("onboarding-content");
  const chatInput = page.getByPlaceholder("Ask a question...");

  await Promise.race([
    onboardingContent.waitFor({ state: "visible", timeout: 30000 }),
    chatInput.waitFor({ state: "visible", timeout: 30000 }),
  ]);

  expect(
    (await onboardingContent.isVisible()) || (await chatInput.isVisible()),
  ).toBeTruthy();
});
