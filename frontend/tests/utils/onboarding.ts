import { expect, type Page } from "@playwright/test";
import path from "path";

export type LLMProvider = "openai" | "anthropic" | "watsonx" | "ollama";
export type EmbeddingProvider = "openai" | "watsonx" | "ollama";

const ONBOARDING_MODELS: Record<string, { llm: string; embedding?: string }> = {
  openai: { llm: "gpt-4o-mini", embedding: "text-embedding-3-small" },
  anthropic: { llm: "claude-sonnet-4-5" },
  watsonx: { llm: "ibm/granite-3-8b-instruct" },
  ollama: { llm: "llama3" },
};

export async function completeOnboarding(
  page: Page,
  {
    llmProvider = "openai",
    embeddingProvider = "openai",
    reset = false,
  }: {
    llmProvider?: LLMProvider;
    embeddingProvider?: EmbeddingProvider;
    reset?: boolean;
  } = {},
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

  if (reset) {
    const response = await page.request.post("/api/onboarding/rollback");
    if (!response.ok() && response.status() !== 400) {
      const text = await response.text();
      throw new Error(`Failed to rollback onboarding: ${text}`);
    }
    await page.reload();
  }

  // Wait for either onboarding to be complete or onboarding content to be visible
  const completedLocator = page.getByTestId("onboarding-completed");
  const contentLocator = page.getByTestId("onboarding-content");

  try {
    await expect(completedLocator.or(contentLocator)).toBeVisible({
      timeout: 15000,
    });
  } catch {
    await page.reload();
    await expect(completedLocator.or(contentLocator)).toBeVisible({
      timeout: 15000,
    });
  }

  const isCompleted = await completedLocator.isVisible();
  const isFirstStep = await page
    .getByTestId("language-model-selector")
    .isVisible();

  if (isCompleted && !reset) {
    return;
  }

  const needsRollback = reset && (isCompleted || !isFirstStep);

  if (needsRollback) {
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
    await page.reload();
    // After rollback and reload, we must see the onboarding content
    await expect(contentLocator).toBeVisible({ timeout: 15000 });
  }

  const setupProvider = async (provider: string, isEmbedding: boolean) => {
    const modelSelectorId = isEmbedding
      ? "embedding-model-selector"
      : "language-model-selector";
    const selector = page.getByTestId(modelSelectorId);

    await expect(selector).toBeEnabled({ timeout: 30000 });
    await selector.click();

    const catalogModel =
      ONBOARDING_MODELS[provider]?.[isEmbedding ? "embedding" : "llm"];
    if (catalogModel) {
      const option = page.getByTestId(`model-option-${catalogModel}`);
      await expect(option).toBeVisible({ timeout: 15000 });
      await option.click();
    } else {
      const customName =
        provider === "ollama"
          ? "nomic-embed-text"
          : "ibm/slate-125m-english-rtrvr";
      const search = page.getByPlaceholder("Search model...");
      await search.fill(customName);
      await page
        .getByTestId(`model-custom-option-${customName}`)
        .last()
        .click();
    }

    if (provider !== "ollama") {
      const getFromEnvSwitch = page.getByTestId("get-from-env-switch");

      if (await getFromEnvSwitch.isVisible()) {
        if (await getFromEnvSwitch.isChecked()) {
          await getFromEnvSwitch.click();
        }
        await expect(getFromEnvSwitch).not.toBeChecked();
      }

      const apiKeyField = page.getByTestId("api-key");
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

    const completeButton = page.getByTestId("onboarding-complete-button");
    await expect(completeButton).toBeEnabled({ timeout: 30000 });
    await completeButton.click();

    const doneLocator = page.getByText("Done");
    const errorLocator = page.getByTestId("onboarding-error");

    await expect(
      page.getByText("Thinking").or(doneLocator).or(errorLocator),
    ).toBeVisible();

    await expect(doneLocator.or(errorLocator)).toBeVisible({
      timeout: isEmbedding ? 120000 : 60000,
    });

    if (await errorLocator.isVisible()) {
      const errorText = await errorLocator.innerText();
      throw new Error(`Onboarding step failed: ${errorText}`);
    }
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
  const openRagAnswer = page.getByText("is an open-source package");
  await expect(page.getByText("Thinking").or(openRagAnswer)).toBeVisible({
    timeout: 60000,
  });
  await expect(openRagAnswer).toBeVisible({
    timeout: 60000,
  });

  // 4. Add your document
  await expect(page.getByText("Lastly, let's add your data.")).toBeVisible({
    timeout: 30000,
  });
  await page.waitForTimeout(2000);
  await expect(page.getByTestId("upload-button")).toBeVisible();

  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByTestId("upload-button").click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(
    path.join(__dirname, "../assets", "test-document.md"),
  );

  const uploadDoneLocator = page.getByText("Done");
  const uploadErrorLocator = page.getByTestId("onboarding-upload-error");

  await expect(uploadDoneLocator.or(uploadErrorLocator)).toBeVisible({
    timeout: 120000,
  });

  if (await uploadErrorLocator.isVisible()) {
    const errorText = await uploadErrorLocator.innerText();
    throw new Error(`Onboarding document upload failed: ${errorText}`);
  }

  await expect(page.getByTestId("onboarding-content")).toBeHidden();
}
