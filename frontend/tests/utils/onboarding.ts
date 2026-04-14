import { expect, type Page } from "@playwright/test";
import path from "path";

export type LLMProvider = "openai" | "anthropic" | "watsonx" | "ollama";
export type EmbeddingProvider = "openai" | "watsonx" | "ollama";

export async function completeOnboarding(
  page: Page,
  {
    llmProvider,
    embeddingProvider,
    reset = false,
  }: {
    llmProvider: LLMProvider;
    embeddingProvider: EmbeddingProvider;
    reset?: boolean;
  },
) {
  // Fast path checks for environment variables
  const checkCredentials = (provider: string) => {
    if (provider === "ollama") return;
    const envVarName = `${provider.toUpperCase()}_API_KEY`;
    if (!process.env[envVarName]) {
      throw new Error(`${envVarName} is not set`);
    }
    if (provider === "watsonx" && !process.env.WATSONX_PROJECT_ID) {
      throw new Error("WATSONX_PROJECT_ID is not set");
    }
  };

  checkCredentials(llmProvider);
  if ((embeddingProvider as string) === "anthropic") {
    throw new Error("Anthropic is not a valid embedding provider");
  }
  checkCredentials(embeddingProvider);

  // Go to the base URL (frontend)
  await page.goto("/");

  // Wait for either onboarding to be complete or onboarding content to be visible
  const completedLocator = page.getByTestId("onboarding-completed");
  const contentLocator = page.getByTestId("onboarding-content");

  try {
    await expect(completedLocator.or(contentLocator)).toBeVisible({
      timeout: 15000,
    });
  } catch (error) {
    console.log("Neither onboarding state visible, refreshing page...");
    await page.reload();
    await expect(completedLocator.or(contentLocator)).toBeVisible({
      timeout: 15000,
    });
  }

  const isCompleted = await completedLocator.isVisible();

  if (isCompleted) {
    if (!reset) {
      console.log("Onboarding already complete, skipping...");
      return;
    }

    console.log("Onboarding complete and reset is true, rolling back...");
    const response = await page.request.post("/api/onboarding/rollback");
    if (!response.ok()) {
      const text = await response.text();
      console.error(
        `Rollback failed with status ${response.status()}: ${text}`,
      );
      if (response.status() !== 400) {
        throw new Error(`Failed to rollback onboarding: ${text}`);
      }
    }

    console.log("Refreshing page after rollback...");
    await page.reload();
    // After rollback and reload, we must see the onboarding content
    await expect(contentLocator).toBeVisible({ timeout: 15000 });
  }

  const setupProvider = async (provider: string, isEmbedding: boolean) => {
    const tabId = `${provider}-${isEmbedding ? "embedding" : "llm"}-tab`;
    await page.getByTestId(tabId).click();

    if (provider !== "ollama") {
      const getFromEnvSwitch = page.getByTestId("get-from-env-switch");

      // Check if switch is visible and toggle off to enter explicit key if needed
      if (await getFromEnvSwitch.isVisible()) {
        if (await getFromEnvSwitch.isChecked()) {
          await getFromEnvSwitch.click();
        }
        await expect(getFromEnvSwitch).not.toBeChecked();
      }

      const apiKeyField = page.getByTestId("api-key");
      // For embedding, the key might be automatically populated if it's the same provider
      // but let's ensure it's filled.
      if ((await apiKeyField.isVisible()) && (await apiKeyField.isEnabled())) {
        const apiKey = process.env[`${provider.toUpperCase()}_API_KEY`];
        await apiKeyField.fill(apiKey!);
      }

      if (provider === "watsonx") {
        const projectIdField = page.getByTestId("project-id");
        if (
          (await projectIdField.isVisible()) &&
          (await projectIdField.isEnabled())
        ) {
          const projectId = process.env.WATSONX_PROJECT_ID;
          await projectIdField.fill(projectId!);
        }
      }
    }

    // Model selection
    // Some providers might have models loaded immediately, some might take time
    const advancedBtn = page.getByTestId("advanced-settings-button");
    if (await advancedBtn.isVisible()) {
      await advancedBtn.click();
    }

    const modelSelectorId = isEmbedding
      ? "embedding-model-selector"
      : "language-model-selector";
    const selector = page.getByTestId(modelSelectorId);

    // Wait for the selector to be enabled (models loaded)
    await expect(selector).toBeEnabled({ timeout: 30000 });
    await selector.click();

    // Select the first available model
    await expect(page.getByTestId(/^model-option-/).first()).toBeVisible();
    await page
      .getByTestId(/^model-option-/)
      .first()
      .click();

    // Complete this step
    await page.getByTestId("onboarding-complete-button").click();

    await expect(page.getByText("Thinking")).toBeVisible();
    await expect(page.getByText("Done")).toBeVisible({
      timeout: isEmbedding ? 120000 : 60000,
    });
  };

  // 1. LLM configuration
  await setupProvider(llmProvider, false);

  // 2. Embeddings configuration
  await setupProvider(embeddingProvider, true);

  // 3. What is OpenRAG (Tutorial)
  await expect(
    page.getByText("Excellent, let's move on to learning the basics."),
  ).toBeVisible();

  await page.waitForTimeout(2000);

  await expect(page.getByTestId("suggestion-0")).toBeVisible();
  await page.getByTestId("suggestion-0").click();

  await expect(page.getByTestId("user-message").first()).toHaveText(
    "What is OpenRAG?",
  );
  await expect(page.getByText("Thinking")).toBeVisible();
  await expect(page.getByText("is an open-source package")).toBeVisible({
    timeout: 60000,
  });

  // 4. Add your document
  await expect(page.getByText("Lastly, let's add your data.")).toBeVisible();
  await page.waitForTimeout(2000);
  await expect(page.getByTestId("upload-button")).toBeVisible();

  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByTestId("upload-button").click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(
    path.join(__dirname, "../assets", "test-document.md"),
  );

  await expect(page.getByText("Done")).toBeVisible({ timeout: 60000 });
  await expect(page.getByTestId("onboarding-content")).toBeHidden();
}
