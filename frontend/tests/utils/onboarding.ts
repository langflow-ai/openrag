import { expect, type Page } from "@playwright/test";
import path from "path";
import { ACTIVE_PROVIDER_CONFIG } from "../config/provider";

export type LLMProvider =
  | "azure"
  | "openai"
  | "anthropic"
  | "watsonx"
  | "ollama";
export type EmbeddingProvider = "azure" | "openai" | "watsonx" | "ollama";

function getProviderKey(providerName: string): LLMProvider {
  switch (providerName) {
    case "Azure OpenAI":
      return "azure";
    case "IBM watsonx.ai":
      return "watsonx";
    case "Ollama":
      return "ollama";
    case "Anthropic":
      return "anthropic";
    default:
      return "openai";
  }
}

const activeProviderKey = getProviderKey(ACTIVE_PROVIDER_CONFIG.provider);

const defaultLlmProvider: LLMProvider =
  ((process.env.LLM_PROVIDER || "").trim().toLowerCase() as LLMProvider) ||
  activeProviderKey;

const defaultEmbeddingProvider: EmbeddingProvider =
  ((process.env.EMBEDDING_PROVIDER || "")
    .trim()
    .toLowerCase() as EmbeddingProvider) ||
  (activeProviderKey === "anthropic"
    ? "openai"
    : (activeProviderKey as EmbeddingProvider));

export async function completeOnboarding(
  page: Page,
  {
    llmProvider = defaultLlmProvider,
    embeddingProvider = defaultEmbeddingProvider,
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
    if (provider === "azure") {
      const key = process.env.AZURE_OPENAI_API_KEY || process.env.AZURE_API_KEY;
      const endpoint =
        process.env.AZURE_OPENAI_ENDPOINT ||
        process.env.AZURE_OPENAI_API_BASE ||
        process.env.AZURE_API_BASE;
      if (!key) throw new Error("AZURE_OPENAI_API_KEY is not set");
      if (!endpoint) throw new Error("AZURE_OPENAI_ENDPOINT is not set");
      return;
    }
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
  const isFirstStep =
    (await page
      .getByTestId("openai-llm-tab")
      .isVisible()
      .catch(() => false)) ||
    (await page
      .getByTestId("azure-llm-tab")
      .isVisible()
      .catch(() => false));

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
    const tabId = `${provider}-${isEmbedding ? "embedding" : "llm"}-tab`;
    await page.getByTestId(tabId).click();

    if (provider === "azure") {
      const endpoint =
        process.env.AZURE_OPENAI_ENDPOINT ||
        process.env.AZURE_OPENAI_API_BASE ||
        process.env.AZURE_API_BASE ||
        "";
      const key =
        process.env.AZURE_OPENAI_API_KEY || process.env.AZURE_API_KEY || "";
      const baseInput = page.locator(
        "#onboarding-azure-api_base, [data-testid='endpoint']",
      );
      if ((await baseInput.isVisible()) && (await baseInput.isEnabled())) {
        const val = await baseInput.inputValue();
        if (!val && endpoint) {
          await baseInput.fill(endpoint);
        }
      }
      const keyInput = page.locator(
        "#onboarding-azure-api_key, [data-testid='api-key']",
      );
      if ((await keyInput.isVisible()) && (await keyInput.isEnabled())) {
        const val = await keyInput.inputValue();
        if (!val && key) {
          await keyInput.fill(key);
        }
      }
    } else if (provider !== "ollama") {
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

    // Select preferred model if available, else first option
    const preferredModel =
      provider === activeProviderKey
        ? isEmbedding
          ? ACTIVE_PROVIDER_CONFIG.embedding
          : ACTIVE_PROVIDER_CONFIG.language
        : isEmbedding
          ? process.env.EMBEDDING_MODEL ||
            (provider === "azure" ? "text-embedding-3-small" : undefined)
          : process.env.LLM_MODEL ||
            (provider === "azure" ? "gpt-4.1" : undefined);

    let selected = false;
    if (preferredModel) {
      const searchInput = page.getByPlaceholder("Search model...");
      await searchInput.fill(preferredModel);
      const preferredOption = page.getByTestId(
        `model-option-${preferredModel}`,
      );
      if (
        await preferredOption.isVisible({ timeout: 2000 }).catch(() => false)
      ) {
        await preferredOption.click();
        selected = true;
      } else {
        await searchInput.clear();
      }
    }
    if (!selected) {
      await expect(page.getByTestId(/^model-option-/).first()).toBeVisible();
      await page
        .getByTestId(/^model-option-/)
        .first()
        .click();
    }

    // Complete this step
    await page.getByTestId("onboarding-complete-button").click();

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
