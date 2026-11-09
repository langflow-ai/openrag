import { expect, test } from "@playwright/test";
import { GREETING_TEXT_PATTERN } from "../../lib/greeting";
import { completeOnboarding } from "../utils/onboarding";

test("can complete onboarding with configured provider", async ({ page }) => {
  await completeOnboarding(page, {
    reset: true,
  });

  // Chat page — greeting is time/day/random, so don't pin a single phrase.
  await expect(page.getByTestId("chat-input")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByText(GREETING_TEXT_PATTERN)).toBeVisible({
    timeout: 30000,
  });

  await expect(
    page.getByTestId("conversation-button-What is OpenRAG?").first(),
  ).toBeVisible();

  await expect(page.getByTestId("selected-knowledge-filter")).toContainText(
    "test-document",
  );

  await page
    .getByTestId("chat-input")
    .fill("What is the ID of verification of the document?");

  await page.getByTestId("send-button").click();

  const verificationAnswer = page.getByText("OPENRAG-GENERIC-ASSET-001");
  await expect(page.getByText("Thinking").or(verificationAnswer)).toBeVisible({
    timeout: 60000,
  });
  await expect(verificationAnswer).toBeVisible({
    timeout: 60000,
  });

  await expect(page.getByTestId(/^suggestion-/)).toHaveCount(3, {
    timeout: 20000,
  });
});
