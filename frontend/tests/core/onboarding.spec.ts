/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import { expect, test } from "@playwright/test";
import { completeOnboarding } from "../utils/onboarding";

test("can configure OpenAI provider", async ({ page }) => {
  await completeOnboarding(page, {
    llmProvider: "openai",
    embeddingProvider: "openai",
    reset: true,
  });

  // Chat page

  await expect(page.getByText("How can I assist?")).toBeVisible({
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
