import { expect, Locator, Page } from "@playwright/test";
import path from "path";
import logger from "../utils/logger";
import { getBaseUrl, navigateToChat } from "../utils/navigation";

export class Chat {
  // Locators - defined at class level for better maintainability
  private readonly chatLink = () =>
    this.page.getByRole("link", { name: "Chat" });
  private readonly plusButton = () =>
    this.page.locator('div[role="presentation"] button').filter({
      has: this.page.locator("svg.lucide-plus"),
    });
  private readonly questionInput = () =>
    this.page.getByRole("textbox", { name: "Ask a question..." });
  private readonly lastMarkdownResponse = () =>
    this.page.locator(".markdown.prose").last();
  private readonly lastMarkdownDiv = () =>
    this.page.locator("div.markdown").last();
  private readonly filterButton = () =>
    this.page.locator('button[data-filter-button="true"]');
  private readonly noFilterOption = () =>
    this.page.getByText("No knowledge filter");
  private readonly htmlElement = () => this.page.locator("html");
  private readonly mainContent = () =>
    this.page.locator('main, [role="main"], body').first();
  private readonly deleteConversationMenuItem = () =>
    this.page.getByRole("menuitem", { name: /delete conversation/i });
  private readonly deleteButton = () =>
    this.page.getByRole("button", { name: /^delete$/i });
  private readonly conversationDeletedToast = () =>
    this.page.getByText(/conversation deleted successfully/i);

  /**
   * Get locator for a filter option by name
   * @param filterName - Name of the filter
   * @returns Locator for the filter option
   */
  private getFilterOption(filterName: string): Locator {
    return this.page.getByText(filterName, { exact: true });
  }

  /**
   * Get locator for tool call by pattern
   * @returns Locator for the tool call element
   */
  private getToolCallLocator(): Locator {
    return this.page
      .getByText(/Function Call:.*opensearch_url_ingestion_flow/i)
      .last();
  }

  /**
   * Get locator for chat row by title
   * @param chatTitle - The title of the chat
   * @returns Locator for the chat row
   */
  private getChatRow(chatTitle: string): Locator {
    const cleanTitle =
      chatTitle.length > 35 ? chatTitle.substring(0, 35) : chatTitle;
    return this.page
      .locator("button")
      .filter({
        has: this.page.getByText(cleanTitle, { exact: false }),
      })
      .first();
  }

  constructor(private page: Page) {}

  async open() {
    await this.chatLink().click();
  }

  /**
   * Open a fresh chat by navigating directly to the chat URL
   * This automatically opens a new chat session
   */
  async openNewChat() {
    const baseUrl = getBaseUrl().replace(/\/$/, "");
    await this.page.goto(`${baseUrl}/chat`);
    // Wait for the question input to be ready and for any background init calls to settle
    await this.page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await this.questionInput().waitFor({ state: "visible", timeout: 15000 });
  }

  /**
   * Ask a question in the chat and wait for the complete response
   * Uses API interception with UI fallback
   * @param question - The question to ask
   * @param timeout - Maximum time to wait for response (default: 60000ms)
   * @returns The complete response text from the assistant
   */
  async askQuestion(
    question: string,
    timeout: number = 120000,
  ): Promise<string> {
    const input = this.questionInput();
    let fullResponse = "";
    // Fill the input first, then set up the intercept just before submitting.
    // This prevents catching background /api/langflow calls (e.g. suggestions/init)
    // that fire when the chat page loads.
    await input.fill(question);
    // Set up response intercept — matches only POST requests whose body contains
    // the question text, so background/suggestion calls are ignored.
    const responsePromise = this.page.waitForResponse(
      async (response) => {
        if (
          !response.url().includes("/api/langflow") ||
          response.request().method() !== "POST"
        ) {
          return false;
        }
        try {
          const body = response.request().postData() || "";
          return body.includes(question.substring(0, 30));
        } catch {
          return true; // body not readable — accept it as a fallback
        }
      },
      { timeout },
    );
    await this.page.keyboard.press("Enter");
    const response = await responsePromise;
    try {
      const raw = await response.text();
      const lines = raw.split("\n").filter((line) => line.trim());
      for (const line of lines) {
        try {
          const chunk = JSON.parse(line);
          if (chunk.delta?.content) {
            fullResponse += chunk.delta.content;
          }
          if (chunk.response?.text) {
            fullResponse = chunk.response.text; // final override
          }
        } catch {
          // ignore malformed chunks
        }
      }
    } catch {
      // fallback to UI
    }

    // Always wait for the UI response to be visible and stable
    const lastResponse = this.lastMarkdownResponse();
    await lastResponse.waitFor({ state: "visible", timeout });

    // Retrieve text content from the enclosing message bubble to ensure both LLM text and citations/filenames are included
    const messageContainer = lastResponse.locator(
      'xpath=ancestor::div[contains(@class, "flex-1")][1]',
    );
    const uiText = (await messageContainer.textContent()) || "";
    if (uiText) {
      fullResponse = uiText;
    }

    return fullResponse.trim();
  }

  /**
   * Ingest a URL via chat and capture tool call data
   * @param url - The URL to ingest
   * @returns Object containing the tool call locator and captured tool data
   */
  async ingestUrl(url: string): Promise<{
    toolCall: Locator;
    toolData: any;
    fullResponse: string;
  }> {
    const input = this.questionInput();
    let capturedToolData: any = null;
    let fullResponseText = "";

    // Collect ALL /api/langflow POST responses until we find tool call data or the
    // streaming response is complete. A single waitForResponse resolves on the first
    // matching call (often a background/init call), so we use a route listener instead.
    const collectedResponses: string[] = [];
    const responseHandler = async (response: any) => {
      if (
        !response.url().includes("/api/langflow") ||
        response.request().method() !== "POST"
      )
        return;
      try {
        collectedResponses.push(await response.text());
      } catch {
        /* ignore */
      }
    };
    this.page.on("response", responseHandler);

    try {
      await input.fill(`Please ingest this URL: ${url}`);
      await this.page.keyboard.press("Enter");

      // Wait for the full streaming response to stabilise in the UI
      await this.waitForStreamingResponse(120000);
    } finally {
      // Stop collecting responses
      this.page.off("response", responseHandler);
    }

    // Parse all collected API responses for tool call data and response text
    for (const raw of collectedResponses) {
      const lines = raw.split("\n").filter((line) => line.trim());
      for (const line of lines) {
        try {
          const chunk = JSON.parse(line);
          // Capture tool call data (first occurrence wins)
          if (
            !capturedToolData &&
            chunk.type === "response.output_item.done" &&
            chunk.item?.type === "tool_call"
          ) {
            capturedToolData = chunk.item;
          }
          // Build full response text
          if (chunk.delta?.content) {
            fullResponseText += chunk.delta.content;
          }
          if (chunk.response?.text) {
            fullResponseText = chunk.response.text;
          }
        } catch {
          // ignore malformed chunks
        }
      }
    }

    // Fallback: read response text from the UI if API parsing yielded nothing
    if (!fullResponseText) {
      fullResponseText =
        (await this.lastMarkdownResponse()
          .textContent()
          .catch(() => "")) || "";
    }

    // The "Function Call:" label in the UI is optional — the app may not render it
    // for all tool invocations. Use it when present; fall back to the locator object.
    const toolCall = this.getToolCallLocator();
    const toolCallVisible = await toolCall
      .isVisible({ timeout: 3000 })
      .catch(() => false);
    if (!toolCallVisible) {
      logger.info(
        `  ℹ️  "Function Call:" UI label not visible — relying on captured API tool data`,
      );
    }

    return {
      toolCall,
      toolData: capturedToolData,
      fullResponse: fullResponseText.trim(),
    };
  }

  async isToolFailed(toolCall: Locator): Promise<boolean> {
    const container = toolCall.locator(
      'xpath=ancestor::div[contains(@class,"border")]',
    );
    const text = await container.textContent();
    return /error|failed|timeout/i.test(text || "");
  }

  /**
   * Apply a knowledge filter in the chat
   * @param filterName - Name of the filter to apply
   */
  async applyKnowledgeFilter(filterName: string) {
    const filterBtn = this.filterButton();
    await filterBtn.click();
    await this.page.waitForTimeout(500);
    const filterOption = this.getFilterOption(filterName);
    await expect(filterOption).toBeVisible({ timeout: 5000 });
    await filterOption.click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Remove the currently applied knowledge filter
   */
  async removeKnowledgeFilter() {
    const filterBtn = this.filterButton();
    await filterBtn.click();
    await this.page.waitForTimeout(500);
    const noFilter = this.noFilterOption();
    await expect(noFilter).toBeVisible({ timeout: 5000 });
    await noFilter.click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Check if a knowledge filter exists in the filter list
   * @param filterName - Name of the filter to check
   * @returns true if filter exists, false otherwise
   */
  async isFilterAvailable(filterName: string): Promise<boolean> {
    const filterBtn = this.filterButton();
    await filterBtn.click();
    await this.page.waitForTimeout(500);
    try {
      const filterOption = this.getFilterOption(filterName);
      const isVisible = await filterOption.isVisible({ timeout: 2000 });
      // Close the filter dropdown
      await filterBtn.click();
      await this.page.waitForTimeout(500);
      return isVisible;
    } catch {
      // Close the filter dropdown
      await filterBtn.click();
      await this.page.waitForTimeout(500);
      return false;
    }
  }

  /**
   * Upload a file in the chat section
   * @param filePath - Path to the file to upload
   * @returns The filename that was uploaded
   */
  async ingestFileInChat(filePath: string) {
    logger.info(`Uploading file from chat: ${filePath}`);
    const fileName = path.basename(filePath);
    const [fileChooser] = await Promise.all([
      this.page.waitForEvent("filechooser"),
      this.plusButton().click(),
    ]);
    await fileChooser.setFiles(filePath);
    logger.info(`File uploaded and ready for querying: ${fileName}`);
    return fileName;
  }

  /**
   * Verify uploaded file in the chat section
   * @param fileName - File name
   */
  async verifyFileInChat(fileName: string) {
    const uploadedFile = this.page.locator("p.text-muted-foreground").filter({
      hasText: fileName,
    });
    await expect(uploadedFile).toBeVisible({ timeout: 10000 });
    logger.info(`File visible in chat: ${fileName}`);
  }

  /**
   * Wait for a response containing specific text
   * @param text - Text to wait for in the response
   * @param timeout - Maximum time to wait
   */
  async waitForResponseContaining(
    text: string | RegExp,
    timeout: number = 60000,
  ) {
    const response = this.lastMarkdownDiv();
    await expect(response).toBeVisible({ timeout });
    await expect(response).toContainText(text, { timeout });
  }

  /**
   * Get the last response from the chat
   * @param timeout - Maximum time to wait for response
   * @returns The response text
   */
  async getLastResponse(timeout: number = 60000): Promise<string> {
    const response = this.lastMarkdownDiv();
    await expect(response).toBeVisible({ timeout });
    return await response.innerText();
  }

  /**
   * Get the current theme applied to the page
   * @returns 'light' or 'dark' based on the HTML class or data attribute
   */
  async getCurrentTheme(): Promise<"light" | "dark"> {
    const html = this.htmlElement();
    const classList = (await html.getAttribute("class")) || "";
    const dataTheme = (await html.getAttribute("data-theme")) || "";
    if (classList.includes("dark") || dataTheme.includes("dark")) {
      return "dark";
    }
    return "light";
  }

  /**
   * Detect if the UI is SaaS (has profile menu) or OSS (direct theme button)
   * @returns true if SaaS, false if OSS
   */
  private async isSaaSUI(): Promise<boolean> {
    // Check for SaaS profile button with aria-haspopup="menu"
    const switchThemeButton = this.page
      .locator("button")
      .filter({
        has: this.page.locator("svg.lucide-sun, svg.lucide-moon"),
      })
      .first();
    try {
      await switchThemeButton.waitFor({ state: "visible", timeout: 2000 });
      return false;
    } catch {
      return true;
    }
  }

  /**
   * Switch to a specific theme mode
   * Handles both SaaS (profile menu → theme button) and OSS (direct theme button) UIs
   * @param theme - The theme to switch to: 'light' or 'dark'
   */
  async switchTheme(theme: "light" | "dark" | "system") {
    const currentTheme = await this.getCurrentTheme();
    if (currentTheme === theme) {
      logger.info(`Already in ${theme} theme, skipping switch`);
      return;
    }

    const isSaaS = await this.isSaaSUI();
    logger.info(`Detected UI type: ${isSaaS ? "SaaS" : "OSS"}`);

    if (isSaaS) {
      // SaaS: Click profile button first, then theme button
      const profileButton = this.page
        .locator('button[aria-haspopup="menu"]')
        .first();
      await profileButton.click();
      await this.page.waitForTimeout(500);

      // Click the appropriate theme button based on desired theme
      if (theme === "light") {
        const lightButton = this.page.locator(
          'button[data-testid="menu_light_button"]',
        );
        await lightButton.waitFor({ state: "visible", timeout: 5000 });
        await lightButton.click();
      } else if (theme === "dark") {
        const darkButton = this.page.locator(
          'button[data-testid="menu_dark_button"]',
        );
        await darkButton.waitFor({ state: "visible", timeout: 5000 });
        await darkButton.click();
      } else if (theme === "system") {
        const systemButton = this.page.locator(
          'button[data-testid="menu_system_button"]',
        );
        await systemButton.waitFor({ state: "visible", timeout: 5000 });
        await systemButton.click();
      }
      await this.page.keyboard.press("Escape");
    } else {
      // OSS: Direct theme button click (toggles between light/dark)
      const themeButton = this.page
        .locator("button")
        .filter({
          has: this.page.locator("svg.lucide-sun, svg.lucide-moon"),
        })
        .first();

      await themeButton.waitFor({ state: "visible", timeout: 5000 });
      await themeButton.click();
    }

    await this.page.waitForTimeout(1000);
    logger.info(`Switched to ${theme} theme`);
  }

  /**
   * Verify theme colors are applied correctly
   * @param expectedTheme - The expected theme ('light' or 'dark')
   */
  async verifyThemeColors(expectedTheme: "light" | "dark") {
    const main = this.mainContent();
    const backgroundColor = await main.evaluate((el) => {
      return window.getComputedStyle(el).backgroundColor;
    });
    const rgbMatch = backgroundColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (rgbMatch) {
      const [, r, g, b] = rgbMatch.map(Number);
      const brightness = (r + g + b) / 3;
      if (expectedTheme === "dark") {
        expect(brightness).toBeLessThan(128);
      } else {
        expect(brightness).toBeGreaterThan(128);
      }
    }
  }

  /**
   * Delete a chat conversation by its title (first prompt)
   * Finds the latest chat with the given title, hovers to reveal menu, and deletes it
   * @param chatTitle - The title of the chat (first prompt given to the chat)
   * @returns Promise that resolves when deletion is complete
   */
  async deleteChatByTitle(chatTitle: string) {
    logger.info(`Deleting chat: ${chatTitle}`);
    await this.openNewChat();
    const chatRow = this.getChatRow(chatTitle);
    await expect(chatRow).toBeVisible({ timeout: 10000 });
    await chatRow.hover();
    const moreOptionsButton = chatRow.locator('[aria-haspopup="menu"]');
    await expect(moreOptionsButton).toBeVisible({ timeout: 5000 });
    await moreOptionsButton.click();
    await this.deleteConversationMenuItem().click();
    await this.deleteButton().click();
    await expect(this.conversationDeletedToast()).toBeVisible();
    logger.info(`Deleted chat successfully`);
  }

  // ============================================================================
  // METHODS ADDED FOR AUTOMATED TESTING SUITE
  // ============================================================================

  /**
   * Skip the onboarding tour if it appears
   */
  async skipOnboardingTour() {
    const skipButton = this.page.getByRole("button", {
      name: /skip overview/i,
    });
    try {
      await skipButton.waitFor({ timeout: 3000 });
      await skipButton.click();
      await this.page.waitForTimeout(500);
    } catch (_error) {
      // No onboarding tour, continue
    }
  }

  /**
   * Get the number of available chat suggestion buttons (buttons with >= 15 characters text)
   */
  async getSuggestionCount(): Promise<number> {
    const mainChatArea = this.page.locator('main, [role="main"]').first();
    const suggestionButtons = mainChatArea.getByRole("button").filter({
      hasText: /.{15,}/,
    });
    return await suggestionButtons.count();
  }

  /**
   * Click the first available chat suggestion button and return its text
   */
  async clickFirstSuggestion(): Promise<string> {
    const mainChatArea = this.page.locator('main, [role="main"]').first();
    const suggestionButtons = mainChatArea.getByRole("button").filter({
      hasText: /.{15,}/,
    });
    const firstSuggestion = suggestionButtons.first();
    const suggestionText = (await firstSuggestion.textContent()) || "";
    await firstSuggestion.click();
    return suggestionText;
  }

  /**
   * Wait for the streaming markdown response to complete
   */
  async waitForStreamingResponse(maxWaitTimeMs: number = 120000) {
    const responseLocator = this.page.locator("div.markdown").last();
    await expect(responseLocator).toBeVisible({ timeout: 30000 });
    await this.page.waitForTimeout(2000);

    let previousText = "";
    let stableCount = 0;
    const startTime = Date.now();

    while (stableCount < 3 && Date.now() - startTime < maxWaitTimeMs) {
      await this.page.waitForTimeout(1000);
      const currentText = (await responseLocator.textContent()) || "";

      if (currentText.trim() === "Thinking...") {
        continue;
      }

      if (currentText === previousText && currentText.length > 50) {
        stableCount++;
      } else {
        stableCount = 0;
        previousText = currentText;
      }
    }
  }

  /**
   * Check for any function calls and wait for them to complete
   */
  async waitForFunctionCallsComplete(timeout: number = 30000) {
    const functionCalls = this.page.getByText(/Function Call:/i);
    const functionCallCount = await functionCalls.count();
    if (functionCallCount > 0) {
      const completedBadge = this.page.getByText("completed");
      if ((await completedBadge.count()) > 0) {
        await expect(completedBadge.first()).toBeVisible({ timeout });
      }
    }
  }
}
