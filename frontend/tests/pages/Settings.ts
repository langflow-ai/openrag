import { expect, Page } from "@playwright/test";
import config from "../config/test.config";
import logger from "../utils/logger";

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export type SettingsTab =
  | "Connectors"
  | "Providers"
  | "Langflow"
  | "Connectors Permission";

export class Settings {
  // Locators - defined at class level for better maintainability
  private readonly settingsLink = () =>
    this.page.getByRole("link", { name: "Settings" });
  private readonly saveIngestSettingsButton = () =>
    this.page.getByRole("button", { name: /save ingest settings/i });
  private readonly settingsUpdatedToast = () =>
    this.page.getByText(/settings updated successfully/i).first();
  private readonly pictureDescriptionsToggle = () =>
    this.page.getByRole("switch", { name: /picture descriptions/i });
  private readonly tableStructureToggle = () =>
    this.page.getByRole("switch", { name: /table structure/i });
  private readonly ocrToggle = () =>
    this.page.getByRole("switch", { name: /^ocr$/i });
  private readonly chunkSizeInput = () => this.page.getByLabel(/chunk size/i);
  private readonly chunkOverlapInput = () =>
    this.page.getByLabel(/chunk overlap/i);
  private readonly watsonxProjectIDInput = () =>
    this.page.locator("#project-id");
  private readonly apiKeyInput = () => this.page.locator("#api-key");
  private readonly watsonxEndPointCombobox = () =>
    this.page.getByRole("combobox");
  private readonly saveModelProviderButton = () =>
    this.page.getByRole("button", { name: "Save" });
  private readonly removeModelProviderButton = () =>
    this.page.getByRole("button", { name: "Remove" });
  private readonly removeAnywayButton = () =>
    this.page.getByRole("button", { name: "Remove Anyway" });
  private readonly watsonxConnectionErrorMessage = () =>
    this.page.getByText("Connection failed. Check your configuration.");

  /**
   * Get locator for configure button by provider name
   * @param providerName - Name of the model provider
   * @returns Locator for the configure button
   */
  private getConfigureButton(providerName: string) {
    return this.page
      .locator("div.rounded-xl, div.border-border.group")
      .filter({ hasText: providerName })
      .getByRole("button", { name: "Configure" });
  }

  /**
   * Get locator for setup heading by provider name
   * @param providerName - Name of the model provider
   * @returns Locator for the setup heading
   */
  private getSetupHeading(providerName: string) {
    return this.page.getByRole("heading", { name: providerName });
  }

  /**
   * Get locator for watsonx option by value
   * Uses data-testid for precise, strict-mode-safe matching
   * @param value - The option value (URL string)
   * @returns Locator for the option
   */
  private getWatsonxOption(value: string) {
    return this.page.getByTestId(`model-option-${value}`);
  }

  /**
   * Get locator for toast message by text
   * @param message - The toast message text
   * @returns Locator for the toast
   */
  private getToastByText(message: string) {
    return this.page
      .locator("[data-sonner-toast]")
      .locator("[data-title]", { hasText: message });
  }

  /**
   * Get locator for edit setup button by provider name
   * @param providerName - Name of the model provider
   * @returns Locator for the edit setup button
   */
  private getEditSetupButton(providerName: string) {
    return this.page
      .locator("div.rounded-xl, div.border-border.group")
      .filter({ hasText: providerName })
      .getByRole("button", { name: "Edit Setup" });
  }

  /**
   * Get locator for remove config button
   * @returns Locator for the remove button in confirmation dialog
   */
  private getRemoveConfigButton() {
    return this.page
      .locator("div", { hasText: "Remove configuration?" })
      .getByRole("button", { name: "Remove" });
  }

  /**
   * Get locator for model dropdown by section name
   * @param section - The section name (e.g., "Chat Model", "Embedding Model")
   * @returns Locator for the dropdown
   */
  private getModelDropdown(section: string) {
    return this.page
      .getByText(new RegExp(escapeRegExp(section), "i"))
      .locator("..")
      .getByRole("combobox");
  }

  /**
   * Get locator for focused search model input
   * @returns Locator for the search input
   */
  private getSearchModelInput() {
    let search = this.page.locator(
      'input[placeholder="Search model..."]:focus',
    );
    return search;
  }

  /**
   * Get locator for search model input (fallback)
   * @returns Locator for the search input
   */
  private getSearchModelInputFallback() {
    return this.page.locator('input[placeholder="Search model..."]').first();
  }

  /**
   * Get locator for model option by name
   * @param model - The model name
   * @returns Locator for the option
   */
  private getModelOption(model: string) {
    return this.page.getByRole("option", {
      name: new RegExp(`^${escapeRegExp(model)}$`),
    });
  }

  /**
   * Get locator for a settings tab by name
   * @param tabName - The tab name to locate
   * @returns Locator for the tab button
   */
  private getSettingsTab(tabName: SettingsTab) {
    return this.page.getByRole("tab", { name: tabName });
  }

  constructor(private page: Page) {}

  /**
   * Click a Settings page tab
   * @param tabName - The tab to click: 'Connectors' | 'Providers' | 'Langflow' | 'Connectors Permission'
   */
  async clickTab(tabName: SettingsTab) {
    logger.info(`Clicking Settings tab: ${tabName}`);
    await this.open();
    const tab = this.getSettingsTab(tabName);
    await expect(tab).toBeVisible({ timeout: 10000 });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true", {
      timeout: 10000,
    });
    logger.info(`Settings tab "${tabName}" is now active`);
  }

  async open() {
    // If already on the settings page, nothing to do
    if (this.page.url().includes("/settings")) {
      return;
    }
    // Navigate to settings
    const settingsLnk = this.settingsLink();
    await settingsLnk.click();
    // Wait for the settings tabs to appear (visible on all settings tabs)
    await expect(
      this.page.getByRole("tab", { name: "Connectors", exact: true }),
    ).toBeVisible({ timeout: 15000 });
  }

  async saveIngestSettings() {
    const saveButton = this.saveIngestSettingsButton();
    await expect(saveButton).toBeVisible();
    await expect(saveButton).toBeEnabled({ timeout: 10000 });
    await saveButton.click();
    await expect(this.settingsUpdatedToast()).toBeVisible({ timeout: 120000 });
  }

  async setPictureDescriptions(enabled: boolean) {
    await this.open();
    const toggle = this.pictureDescriptionsToggle();
    await toggle.scrollIntoViewIfNeeded();
    const state = await toggle.getAttribute("data-state");
    const isChecked = state === "checked";
    if (isChecked !== enabled) {
      await toggle.click();
      await this.saveIngestSettings();
    }
  }

  async setTableStructure(enabled: boolean) {
    await this.open();
    const toggle = this.tableStructureToggle();
    await toggle.scrollIntoViewIfNeeded();
    const state = await toggle.getAttribute("data-state");
    const isChecked = state === "checked";
    if (isChecked !== enabled) {
      await toggle.click();
      await this.saveIngestSettings();
    }
  }

  async setOCR(enabled: boolean) {
    await this.open();
    const toggle = this.ocrToggle();
    await toggle.scrollIntoViewIfNeeded();
    const state = await toggle.getAttribute("data-state");
    const isChecked = state === "checked";
    if (isChecked !== enabled) {
      await toggle.click();
      await this.saveIngestSettings();
    }
  }

  async selectModel(section: string, model: string) {
    await this.open();
    const dropdown = this.getModelDropdown(section);
    await dropdown.scrollIntoViewIfNeeded();
    const currentText = (await dropdown.textContent())?.toLowerCase() || "";
    if (currentText.includes(model.toLowerCase())) return;
    await dropdown.click();
    let search = this.getSearchModelInput();
    if ((await search.count()) === 0) {
      // fallback safety
      search = this.getSearchModelInputFallback();
    }
    await expect(search).toBeVisible({ timeout: 5000 });
    await search.fill(model);
    const option = this.getModelOption(model);
    await expect(option).toBeVisible({ timeout: 10000 });
    await option.waitFor({ state: "visible" });
    await option.click({ timeout: 5000 });
    await option.waitFor({ state: "detached" }).catch(() => {});
    await this.settingsUpdatedToast()
      .waitFor({ timeout: 20000 })
      .catch(() => {});
    // Wait for the app to settle after model change (especially embedding model triggers re-indexing)
    await this.page
      .waitForLoadState("networkidle", { timeout: 30000 })
      .catch(() => {});
    await this.page.waitForTimeout(15000); // Wait for background operations to run
  }

  /**
   * Update chunk size and overlap settings
   * @param chunkSize - Chunk size value (e.g., "500")
   * @param chunkOverlap - Chunk overlap value (e.g., "50")
   */
  async updateChunkSettings(chunkSize: string, chunkOverlap: string) {
    await this.open();

    // Find and update chunk size input
    const chunkSizeInp = this.chunkSizeInput();
    await chunkSizeInp.scrollIntoViewIfNeeded();

    // Get current value to check if change is needed
    const currentChunkSize = await chunkSizeInp.inputValue();
    const currentChunkOverlap = await this.chunkOverlapInput().inputValue();

    // If values are already set, skip the update
    if (
      currentChunkSize === chunkSize &&
      currentChunkOverlap === chunkOverlap
    ) {
      logger.info(
        `Chunk settings already set to size=${chunkSize}, overlap=${chunkOverlap}. Skipping update.`,
      );
      return;
    }

    // Update chunk size
    await chunkSizeInp.click();
    await chunkSizeInp.fill(chunkSize);
    await chunkSizeInp.blur();

    // Find and update chunk overlap input
    const chunkOverlapInp = this.chunkOverlapInput();
    await chunkOverlapInp.scrollIntoViewIfNeeded();
    await chunkOverlapInp.click();
    await chunkOverlapInp.fill(chunkOverlap);
    await chunkOverlapInp.blur();

    // Wait a moment for the form to detect changes
    await this.page.waitForTimeout(1000);

    // Save settings
    await this.saveIngestSettings();
  }

  /**
   * Configure IBM watsonx.ai model provider
   */
  async configureWatsonxai() {
    logger.info("Configuring watsonx.ai settings");
    const configureBtn = this.getConfigureButton("IBM watsonx.ai");
    const editBtn = this.getEditSetupButton("IBM watsonx.ai");
    // If Configure button is visible -> do setup
    if (await configureBtn.isVisible()) {
      await configureBtn.click();
      await expect(this.getSetupHeading("IBM watsonx.ai")).toBeVisible();
      const { url, projectId, apiKey } = config.watsonx;
      await this.watsonxEndPointCombobox().click();
      // Wait for the dropdown to open by polling until any option appears
      await this.page.waitForSelector('[role="option"]', {
        state: "visible",
        timeout: 15000,
      });
      const option = this.getWatsonxOption(url);
      await expect(option).toBeVisible({ timeout: 10000 });
      await option.click();
      await this.watsonxProjectIDInput().fill(projectId);
      await this.apiKeyInput().fill(apiKey);
      await this.saveModelProviderButton().click();
      logger.info("Watsonx.ai configuration completed");
      await expect(
        this.getToastByText("IBM watsonx.ai successfully configured"),
      ).toBeVisible();
      await expect(editBtn).toBeEnabled();
    }
    // Else if already configured -> skip setup
    else if (await editBtn.isVisible()) {
      logger.info("Watsonx.ai already configured. Skipping setup.");
      await expect(editBtn).toBeEnabled();
    }
    // Neither found
    else {
      throw new Error("Neither Configure nor Edit Setup button is visible");
    }
  }

  /**
   * Remove model provider configuration
   */
  async removeModelProviderSetup(modelProvider: string) {
    const editButton = this.getEditSetupButton(modelProvider);
    const configureButton = this.getConfigureButton(modelProvider);
    // If already configured (Edit Setup visible)
    if (await editButton.isVisible()) {
      logger.info(`${modelProvider} is configured. Removing setup...`);
      await editButton.click();
      await this.removeModelProviderButton().click();
      await this.getRemoveConfigButton().click();
      await this.clickRemoveAnywayIfDisplayed();
      await expect(
        this.getToastByText(`${modelProvider} configuration removed`),
      ).toBeVisible({ timeout: 15000 });
      await this.page.waitForTimeout(10000);
    }
    // If not configured
    else if (await configureButton.isVisible()) {
      logger.info(`${modelProvider} is not configured. Skipping removal.`);
    }
    // Unexpected state
    else {
      throw new Error(
        `No Configure/Edit Setup button found for ${modelProvider}`,
      );
    }
  }

  /**
   * Click the 'Remove Anyway' button if it is displayed.
   * This button appears when removing a provider that has embedded documents,
   * as a secondary confirmation to proceed with removal.
   */
  async clickRemoveAnywayIfDisplayed() {
    const btn = this.removeAnywayButton();
    const isVisible = await btn
      .waitFor({ state: "visible", timeout: 15000 })
      .then(() => true)
      .catch(() => false);
    if (isVisible) {
      logger.info("Remove Anyway button is displayed. Clicking it.");
      await btn.click();
    } else {
      logger.info("Remove Anyway button is not displayed. Skipping.");
    }
  }

  /**
   * Configure Openai model provider
   */
  async configureOpenAPI() {
    logger.info("Configuring Openai settings");
    const configureBtn = this.getConfigureButton("OpenAI");
    const editBtn = this.getEditSetupButton("OpenAI");

    // If Configure button is visible -> do setup
    if (await configureBtn.isVisible()) {
      await configureBtn.click();
      await expect(this.getSetupHeading("OpenAI")).toBeVisible();
      const apiKey = config.openaiApiKey;
      await this.apiKeyInput().fill(apiKey);
      await this.saveModelProviderButton().click();
      logger.info("OpenAI configuration completed");
      await expect(
        this.getToastByText("OpenAI successfully configured"),
      ).toBeVisible();
      await expect(editBtn).toBeEnabled();
    }
    // Else if already configured -> skip setup
    else if (await editBtn.isVisible()) {
      logger.info("OpenAI already configured. Skipping setup.");
      await expect(editBtn).toBeEnabled();
    }
    // Neither found
    else {
      throw new Error("Neither Configure nor Edit Setup button is visible");
    }
  }

  /**
   * Configure IBM watsonx.ai model provider with invalid credentials
   */
  async configureWatsonxaiInvalidCredentials(
    url: string,
    projectId: string,
    apiKey: string,
  ) {
    logger.info("Configuring watsonx.ai settings with invalid credentials");
    const configureBtn = this.getConfigureButton("IBM watsonx.ai");
    // If Configure button is visible -> do setup
    if (await configureBtn.isVisible()) {
      await configureBtn.click();
      await expect(this.getSetupHeading("IBM watsonx.ai")).toBeVisible();
      await this.watsonxEndPointCombobox().click();
      // Wait for the dropdown to open by polling until any option appears
      await this.page.waitForSelector('[role="option"]', {
        state: "visible",
        timeout: 15000,
      });
      const option = this.getWatsonxOption(url);
      await expect(option).toBeVisible({ timeout: 10000 });
      await option.click();
      await this.watsonxProjectIDInput().fill(projectId);
      await this.apiKeyInput().fill(apiKey);
      await this.saveModelProviderButton().click();
      logger.info(
        "Verify that watsonx.ai configuration failed due to invalid credentials",
      );
      await expect(this.watsonxConnectionErrorMessage()).toBeVisible();
    }
  }
}
