import { expect, test } from "@playwright/test";
import path from "path";

test("can configure OpenAI provider", async ({ page }) => {
  const apiKey = process.env.OPENAI_API_KEY;

  if (!apiKey) {
    throw new Error("OPENAI_API_KEY is not set");
  }

  // Go to the base URL (frontend)
  await page.goto("/");

  try {
    // Expect the onboarding content to be visible using the test id.
    await expect(page.getByTestId("onboarding-content")).toBeVisible({
      timeout: 15000,
    });
  } catch (error) {
    console.log("Refreshing page...");
    await page.reload();
    await expect(page.getByTestId("onboarding-content")).toBeVisible({
      timeout: 15000,
    });
  }

  await expect(
    page.getByText("Let's get started by setting up your LLM provider."),
  ).toBeVisible();

  await expect(page.getByTestId("openai-llm-tab")).toBeVisible();
  await expect(page.getByTestId("anthropic-llm-tab")).toBeVisible();
  await expect(page.getByTestId("watsonx-llm-tab")).toBeVisible();
  await expect(page.getByTestId("ollama-llm-tab")).toBeVisible();

  // LLM configuration

  await page.getByTestId("openai-llm-tab").click();

  await expect(page.getByTestId("openai-llm-tab")).toHaveAttribute(
    "aria-selected",
    "true",
  );

  await expect(page.getByTestId("get-from-env-switch")).toBeVisible();

  await expect(page.getByTestId("get-from-env-switch")).toBeChecked();

  await page.getByTestId("get-from-env-switch").click();

  await expect(page.getByTestId("get-from-env-switch")).not.toBeChecked();

  await page.getByTestId("api-key").fill(apiKey);

  await page.getByTestId("advanced-settings-button").click();

  await expect(page.getByTestId("language-model-selector")).toBeEnabled();

  await page.getByTestId("language-model-selector").click();

  const modelOptionsCount = await page.getByTestId(/^model-option-/).count();
  expect(modelOptionsCount).toBeGreaterThan(0);

  await page
    .getByTestId(/^model-option-/)
    .first()
    .click();

  await page.getByTestId("onboarding-complete-button").click();

  await expect(page.getByText("Thinking")).toBeVisible();

  await expect(page.getByText("Done")).toBeVisible({ timeout: 60000 });

  // Embeddings configuration

  await expect(
    page.getByText("Now, let's set up your embedding provider."),
  ).toBeVisible();

  await expect(page.getByTestId("openai-embedding-tab")).toBeVisible();
  await expect(page.getByTestId("anthropic-embedding-tab")).not.toBeVisible();
  await expect(page.getByTestId("watsonx-embedding-tab")).toBeVisible();
  await expect(page.getByTestId("ollama-embedding-tab")).toBeVisible();

  await page.getByTestId("openai-embedding-tab").click();

  await expect(page.getByTestId("openai-embedding-tab")).toHaveAttribute(
    "aria-selected",
    "true",
  );

  await expect(
    page.getByText(
      "Existing OpenAI key detected. You can reuse it or enter a new one.",
    ),
  ).toBeVisible();

  await page.getByTestId("advanced-settings-button").click();

  await expect(page.getByTestId("embedding-model-selector")).toBeEnabled();

  await page.getByTestId("embedding-model-selector").click();

  const embeddingModelOptionsCount = await page
    .getByTestId(/^model-option-/)
    .count();
  expect(embeddingModelOptionsCount).toBeGreaterThan(0);

  await page
    .getByTestId(/^model-option-/)
    .first()
    .click();

  await page.getByTestId("onboarding-complete-button").click();

  await expect(page.getByText("Thinking")).toBeVisible();

  await expect(page.getByText("Done")).toBeVisible({ timeout: 120000 });

  // What is OpenRAG

  await expect(
    page.getByText("Excellent, let's move on to learning the basics."),
  ).toBeVisible();

  await expect(page.getByTestId("suggestion-0")).toBeVisible();

  await expect(page.getByTestId("suggestion-0")).toHaveText("What is OpenRAG?");

  await page.getByTestId("suggestion-0").click();

  await expect(page.getByTestId("user-message").first()).toHaveText(
    "What is OpenRAG?",
  );

  await expect(page.getByText("Thinking")).toBeVisible();

  await expect(page.getByText("OpenRAG is an open-source package")).toBeVisible(
    { timeout: 60000 },
  );

  // Add your document

  await expect(page.getByText("Lastly, let's add your data.")).toBeVisible();

  await expect(page.getByTestId("upload-button")).toBeVisible();

  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByTestId("upload-button").click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(
    path.join(__dirname, "../assets", "test-document.txt"),
  );

  await expect(page.getByText("Done")).toBeVisible({ timeout: 60000 });

  await expect(page.getByTestId("onboarding-content")).toBeHidden();

  // Chat page

  await expect(page.getByText("How can I assist?")).toBeVisible({
    timeout: 30000,
  });

  await expect(
    page.getByTestId("conversation-button-What is OpenRAG?"),
  ).toBeVisible();

  await expect(page.getByTestId(/^suggestion-/)).toHaveCount(3);

  await expect(page.getByTestId("selected-knowledge-filter")).toContainText(
    "test-document",
  );

  await page
    .getByTestId("chat-input")
    .fill("What is the ID of verification of the document?");

  await page.getByTestId("send-button").click();

  await expect(page.getByText("Thinking")).toBeVisible();

  await expect(page.getByText("OPENRAG-GENERIC-ASSET-001")).toBeVisible({
    timeout: 60000,
  });
});
