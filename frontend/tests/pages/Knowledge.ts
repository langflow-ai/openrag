import { expect, Locator, Page } from "@playwright/test";
import path from "path";
import logger from "../utils/logger";

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export class Knowledge {
  // Locators - defined at class level for better maintainability
  private readonly knowledgeLink = () =>
    this.page.getByRole("link", { name: "Knowledge" });
  private readonly projectKnowledgeHeading = () =>
    this.page.getByText("Project Knowledge");
  private readonly searchErrorGeneric = () =>
    this.page.getByText(/search error/i);
  private readonly transportError = () =>
    this.page.getByText(/TransportError.*search_phase_execution_exception/i);
  private readonly embeddingError = () =>
    this.page.getByText(/Failed to embed with model/i);
  private readonly fetchLatestDocsButton = () =>
    this.page.getByRole("button", { name: "Fetch latest docs" });
  private readonly openragDocsRefreshedToast = () =>
    this.page.getByText(/OpenRAG docs were refreshed/i).first();
  private readonly taskCompletedToast = () =>
    this.page.getByText(/task completed/i).first();
  readonly addKnowledgeButton = () =>
    this.page.getByRole("button", { name: /^Add [Kk]nowledge$/i });
  private readonly fileInput = () =>
    this.page.locator('input[type="file"]').first();
  private readonly overwriteButton = () =>
    this.page.getByRole("button", { name: "Overwrite" });
  private readonly fileOption = () =>
    this.page.getByText("File", { exact: true });
  private readonly folderOption = () => this.page.getByText("Folder");
  private readonly firstPageButton = () =>
    this.page.getByRole("button", { name: /first page/i });
  private readonly nextPageButton = () =>
    this.page.getByRole("button", { name: /next page/i });
  private readonly gridContainer = () => this.page.locator(".ag-body-viewport");
  private readonly searchInput = () =>
    this.page.locator('input[placeholder*="Search"]');
  private readonly deleteButton = () =>
    this.page.getByRole("button", { name: "Delete" });
  private readonly deleteDocumentDialog = () =>
    this.page.locator("text=Delete document");
  private readonly confirmDeleteButton = () =>
    this.page.getByRole("button", { name: "Delete" }).last();
  private readonly deleteSuccessToast = () =>
    this.page
      .getByText(
        /successfully deleted \d+ document|document.*deleted|deleted.*document/i,
      )
      .first();
  private readonly knowledgeFiltersHeading = () =>
    this.page.getByText("Knowledge Filters");
  private readonly createFilterButton = () =>
    this.page.locator('button[title="Create New Filter"]');
  private readonly filterNameInput = () =>
    this.page
      .locator("input#filter-name")
      .or(this.page.locator('input[placeholder*="Filter name"]'))
      .first();
  private readonly allSourcesButton = () =>
    this.page.locator("button").filter({ hasText: "All sources" }).first();
  private readonly allSourcesOption = () =>
    this.page
      .locator('[role="option"]')
      .filter({ hasText: "All sources" })
      .first();
  private readonly searchOptionsInput = () =>
    this.page
      .locator('input[placeholder*="Search options"]')
      .or(this.page.locator('input[placeholder*="search"]'))
      .first();
  private readonly createFilterSubmitButton = () =>
    this.page.getByRole("button", { name: /Create Filter/i });
  private readonly deleteFilterButton = () =>
    this.page.getByRole("button", { name: "Delete Filter" });
  private readonly chunkElements = () => this.page.locator("blockquote");
  private readonly grid = () =>
    this.page.locator(".ag-body-horizontal-scroll-viewport");

  /**
   * Get locator for data rows with checkboxes
   * @returns Locator for data rows
   */
  private getDataRows(): Locator {
    return this.page.locator('[role="row"]').filter({
      has: this.page.locator('input[type="checkbox"]'),
    });
  }

  /**
   * Get locator for a row by its row-id attribute
   * @param key - The row-id value
   * @returns Locator for the row
   */
  private getRowById(key: string): Locator {
    return this.page.locator(`[role="row"][row-id="${key}"]`);
  }

  /**
   * Get locator for source cell with exact text match
   * @param key - The text to match
   * @returns Locator for the cell
   */
  private getSourceCellByExactText(key: string): Locator {
    return this.page
      .locator('[col-id="source"]')
      .getByText(new RegExp(`^${escapeRegExp(key)}$`))
      .first();
  }

  /**
   * Get locator for source cell with title attribute
   * @param key - The title value
   * @returns Locator for the cell
   */
  private getSourceCellByTitle(key: string): Locator {
    return this.page.locator(`[col-id="source"] [title="${key}"]`).first();
  }

  /**
   * Get locator for source cell with partial text match
   * @param key - The text to match
   * @returns Locator for the cell
   */
  private getSourceCellByPartialText(key: string): Locator {
    return this.page
      .locator('[col-id="source"]')
      .getByText(key, { exact: false })
      .first();
  }

  /**
   * Get locator for files uploaded successfully message
   * @param count - Number of files
   * @returns Locator for the message
   */
  private getFilesUploadedMessage(count: number): Locator {
    return this.page.getByText(`${count} files uploaded successfully`);
  }

  /**
   * Get locator for source option in filter dropdown
   * @param sourceFileName - Name of the source file
   * @returns Locator for the option
   */
  private getSourceOption(sourceFileName: string): Locator {
    return this.page
      .locator('[role="option"]')
      .filter({ hasText: sourceFileName })
      .first();
  }

  /**
   * Get locator for filter item by name
   * @param filterName - Name of the filter
   * @returns Locator for the filter item
   */
  private getFilterItem(filterName: string): Locator {
    return this.page.locator(`text="${filterName}"`).first();
  }

  /**
   * Get locator for status column in a row
   * @param row - The row locator
   * @returns Locator for the status cell
   */
  private getStatusCell(row: Locator): Locator {
    return row.locator('[col-id="status"]');
  }

  /**
   * Get locator for checkbox in a row
   * @param row - The row locator
   * @returns Locator for the checkbox
   */
  private getRowCheckbox(row: Locator): Locator {
    return row.locator('input[type="checkbox"]');
  }

  constructor(private page: Page) {}

  /**
   * Check if there's a critical search error in the knowledge base
   * Detects two types of errors:
   * 1. OpenSearch database errors (search_phase_execution_exception)
   * 2. Model-specific embedding errors (Failed to embed with model)
   * @throws Error if search error is detected
   */
  private async checkForSearchError() {
    // Wait a moment for any error messages to appear
    await this.page.waitForTimeout(1000);

    // Look for different types of search error messages
    const searchError = this.searchErrorGeneric();
    const transport = this.transportError();
    const embedding = this.embeddingError();

    try {
      // Check if any error message is visible
      const errorCheck = await Promise.race([
        searchError.isVisible().then(async (visible) => {
          if (visible) {
            // Get the full error text to determine the type
            const errorText = await searchError.textContent();
            return { type: "search_error", text: errorText };
          }
          return null;
        }),
        transport.isVisible().then((visible) =>
          visible
            ? {
                type: "transport_error",
                text: "TransportError(503, search_phase_execution_exception)",
              }
            : null,
        ),
        embedding.isVisible().then(async (visible) => {
          if (visible) {
            const errorText = await embedding.textContent();
            return { type: "embedding_error", text: errorText };
          }
          return null;
        }),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), 2000)),
      ]);

      if (errorCheck) {
        // Determine error type and throw appropriate error
        if (
          errorCheck.type === "embedding_error" ||
          errorCheck.text?.includes("Failed to embed")
        ) {
          // Extract model name from error message if possible
          const modelMatch = errorCheck.text?.match(/model\s+([^\s]+)/i);
          const modelName = modelMatch ? modelMatch[1] : "unknown";

          throw new Error(
            `❌ MODEL ERROR: Search failed due to embedding model issue.\n` +
              `   Model: ${modelName}\n` +
              `   Error: ${errorCheck.text}\n` +
              `   This occurs when searching with a model that has documents indexed with it but the model is unavailable or misconfigured.\n` +
              `   Solution: Either fix the model configuration or switch to a different embedding model.`,
          );
        } else {
          // OpenSearch database error
          throw new Error(
            "❌ CRITICAL: Knowledge base search error detected (OpenSearch database issue).\n" +
              "   This error prevents all knowledge base operations.\n" +
              `   Error: ${errorCheck.text}\n` +
              "   Solution: Check OpenSearch service status and configuration.",
          );
        }
      }
    } catch (error) {
      // If it's our custom error, re-throw it
      if (
        error instanceof Error &&
        (error.message.includes("CRITICAL") ||
          error.message.includes("MODEL ERROR"))
      ) {
        throw error;
      }
      // Otherwise, no error found (which is good)
    }
  }

  /**
   * Check if the page is still open and usable
   */
  private isPageClosed(): boolean {
    return this.page.isClosed();
  }

  /**
   * Safe wrapper for waitForTimeout that skips if the page is closed.
   * Prevents "Target page, context or browser has been closed" errors
   * in cleanup/catch blocks after the test has timed out.
   */
  private async safeWait(ms: number): Promise<void> {
    if (this.isPageClosed()) return;
    try {
      await this.page.waitForTimeout(ms);
    } catch {
      // Page was closed during the wait — swallow silently
    }
  }

  async open() {
    // If already on the knowledge page, nothing to do
    if (this.page.url().includes("/knowledge")) {
      await expect(this.projectKnowledgeHeading()).toBeVisible({
        timeout: 15000,
      });
      await this.checkForSearchError();
      return;
    }
    // Wait for any in-progress navigation to settle before clicking
    await this.page
      .waitForLoadState("domcontentloaded", { timeout: 15000 })
      .catch(() => {});
    const link = this.knowledgeLink();
    await expect(link).toBeVisible({ timeout: 15000 });
    await link.click({ timeout: 30000 });
    await expect(this.projectKnowledgeHeading()).toBeVisible({
      timeout: 30000,
    });
    // Automatically check for critical errors every time we open knowledge base
    await this.checkForSearchError();
  }

  /**
   * Click "Fetch latest docs" button to refresh the document list.
   * Waits for the "What is OpenRAG?" document re-ingestion to complete.
   */
  async fetchLatestDocs() {
    if (this.isPageClosed()) return;
    const fetchButton = this.fetchLatestDocsButton();
    await fetchButton.click();
    // Wait for the refresh confirmation toast
    await expect(this.openragDocsRefreshedToast()).toBeVisible({
      timeout: 10000,
    });
    // Brief pause — reduced from 1000 ms to avoid eating into the test budget
    await this.safeWait(500);
    // "Fetch latest docs" triggers re-ingestion of "What is OpenRAG?" document.
    // Wait for its "Task completed" message so we don't confuse it with our own uploads.
    try {
      if (this.isPageClosed()) return;
      await expect(this.taskCompletedToast()).toBeVisible({ timeout: 30000 });
      logger.info(
        `  ⏳ Waiting for "What is OpenRAG?" re-ingestion to complete...`,
      );
      // Wait for the toast to auto-dismiss (~3-5 s); reduced from 6000 ms
      await this.safeWait(4000);
    } catch {
      // No task-completed message appeared — that's fine, just continue
      await this.safeWait(300);
    }
  }

  async ingestFile(
    filePath: string,
    overrideIfExists: boolean = true,
  ): Promise<string> {
    await this.open();
    // Handle both SaaS (lowercase) and OSS (uppercase) versions - use first() to handle multiple matches
    await this.addKnowledgeButton().click();
    const fileName = path.basename(filePath);
    // SaaS shows a dropdown (File / Folder / Google Drive / SharePoint) after clicking Add knowledge.
    // Click "File" if it appears; OSS exposes the file input directly without a dropdown.
    const fileOpt = this.fileOption();
    if (await fileOpt.isVisible().catch(() => false)) {
      await fileOpt.click();
    }
    await this.fileInput().setInputFiles(filePath);

    // Always check for the overwrite dialog — it appears whenever the file already exists
    try {
      const overwriteBtn = this.overwriteButton();
      await overwriteBtn.waitFor({ state: "visible", timeout: 4000 });
      if (overrideIfExists) {
        await expect(overwriteBtn).toBeEnabled({ timeout: 3000 });
        await overwriteBtn.click();
        logger.info(
          `Overwrite dialog detected — overwriting existing file: ${fileName}`,
        );
      } else {
        // Cancel the overwrite: click the Cancel button to dismiss the dialog
        await this.page.getByRole("button", { name: "Cancel" }).click();
        logger.info(
          `Overwrite dialog detected — cancelled (overrideIfExists=false): ${fileName}`,
        );
        return fileName;
      }
    } catch {
      // No overwrite dialog appeared — file is new, continue normally
    }

    // Wait for ingestion task to complete.
    // "task completed" toast may appear and auto-dismiss quickly, or may not appear
    // at all when overwriting an already-indexed file (the app skips re-queuing).
    // Give it a generous window but don't fail if it never shows — the file status
    // check in verifyDocumentActive is the authoritative confirmation.
    const taskCompleted = this.page.getByText(/task completed/i).first();
    await taskCompleted
      .waitFor({ state: "visible", timeout: 180000 })
      .catch(() => {
        logger.info(
          `  ℹ️  "task completed" toast not detected — file may have been processed immediately or toast was dismissed`,
        );
      });

    // Close the "Add Knowledge" dropdown menu by pressing Escape or clicking outside
    await this.page.keyboard.press("Escape");
    await this.page.waitForTimeout(500);
    return fileName;
  }

  async ingestFolder(
    folderPath: string,
    expectedFileCount: number,
    timeout: number = 180000,
  ): Promise<string> {
    await this.open();
    // Handle both SaaS (lowercase) and OSS (uppercase) versions - use first() to handle multiple matches
    await this.addKnowledgeButton().click();
    const folderName = path.basename(folderPath);
    const [fileChooser] = await Promise.all([
      this.page.waitForEvent("filechooser"),
      this.folderOption().click(),
    ]);
    await fileChooser.setFiles(folderPath);
    // ❗ DO NOT click Upload blindly
    await expect(this.getFilesUploadedMessage(expectedFileCount)).toBeVisible({
      timeout,
    });
    await this.page.keyboard.press("Escape");
    return folderName;
  }

  /**
   * Reset pagination to first page
   */
  private async resetToFirstPage() {
    const firstPageBtn = this.firstPageButton();
    try {
      const ariaDisabled = await firstPageBtn.getAttribute("aria-disabled");
      const classAttr = await firstPageBtn.getAttribute("class");
      const isDisabled =
        ariaDisabled === "true" || classAttr?.includes("ag-disabled");
      if (!isDisabled) {
        await firstPageBtn.click();
        await this.page.waitForTimeout(500);
      }
    } catch {
      // Button might not exist or not be clickable, that's fine
    }
  }

  /**
   * Find a row across all pages in the AG Grid.
   * Handles both virtualization scrolling and pagination.
   *
   * Strategy (in priority order):
   *   1. row-id attribute  — AG Grid sets this to the row's primary key; most reliable.
   *   2. Exact text match  — works when the cell text is not truncated.
   *   3. title attribute   — AG Grid often sets title="<full value>" even when the cell
   *                          text is visually truncated by CSS overflow.
   *   4. Partial text      — last resort; avoids false negatives from display trimming.
   *
   * @param key - The text to search for in the row
   * @returns The row locator if found
   * @throws Error if row not found after checking all pages
   */
  async findRowAcrossPages(key: string): Promise<Locator> {
    // Use the search box to filter the grid to the target document.
    // This avoids slow scroll/pagination loops and works even with large document lists.
    const searchInp = this.searchInput();
    if (await searchInp.isVisible()) {
      await searchInp.clear();
      await searchInp.fill(key);
      // Wait for the row-id attribute AG Grid sets to the data key.
      // More reliable than getByText: row-id is a flat attribute on the row element,
      // unaffected by AG Grid's deeply nested virtual DOM cell rendering.
      const rowById = this.getRowById(key);
      const exists = await rowById
        .first()
        .waitFor({ state: "visible", timeout: 10000 })
        .then(() => true)
        .catch(() => false);
      if (!exists) {
        // Not found — clear search and throw immediately
        await searchInp.clear();
        await this.page.waitForTimeout(300);
        throw new Error(`Row with key "${key}" not found across all pages`);
      }
      // Found via search — get the row while the filter is active
      const rowByTitle = this.getSourceCellByTitle(key);
      const rowByExact = this.getSourceCellByExactText(key);
      const rowByPartial = this.getSourceCellByPartialText(key);
      let foundRow: Locator | null = null;
      for (const candidate of [
        rowById.first(),
        rowByTitle,
        rowByExact,
        rowByPartial,
      ]) {
        if (await candidate.isVisible().catch(() => false)) {
          foundRow = candidate.locator(
            'xpath=ancestor-or-self::*[@role="row"][1]',
          );
          // For rowById, it already IS the row
          if (candidate === rowById.first()) foundRow = rowById.first();
          break;
        }
      }
      // Clear search to restore full grid view
      await searchInp.clear();
      await this.page.waitForTimeout(300);
      if (foundRow) return foundRow;
      throw new Error(`Row with key "${key}" not found across all pages`);
    }
    // Fallback: no search box — use original scroll/pagination approach
    // Always reset to first page at the start for consistent behavior
    await this.resetToFirstPage();
    const gridCont = this.gridContainer();
    // Helper: try all four strategies against the currently rendered DOM.
    const tryFind = async (timeout: number): Promise<Locator | null> => {
      // 1. row-id attribute (most reliable — set by AG Grid to the data key)
      const rowById = this.getRowById(key);
      try {
        await expect(rowById.first()).toBeVisible({ timeout });
        return rowById.first();
      } catch {
        // not found by row-id
      }
      // 2. Exact text match inside the source cell
      const exactSourceCell = this.getSourceCellByExactText(key);
      try {
        await expect(exactSourceCell).toBeVisible({ timeout });
        return exactSourceCell.locator('xpath=ancestor::*[@role="row"][1]');
      } catch {
        // not found by exact text
      }
      // 3. title attribute — handles truncated cell display text
      const cellWithTitle = this.getSourceCellByTitle(key);
      try {
        await expect(cellWithTitle).toBeVisible({ timeout });
        return cellWithTitle.locator('xpath=ancestor::*[@role="row"][1]');
      } catch {
        // not found by title
      }
      // 4. Partial / contains match as last resort
      const looseCell = this.getSourceCellByPartialText(key);
      try {
        await expect(looseCell).toBeVisible({ timeout });
        return looseCell.locator('xpath=ancestor::*[@role="row"][1]');
      } catch {
        return null;
      }
    };
    let pagesChecked = 0;
    const MAX_PAGES = 50;
    while (pagesChecked < MAX_PAGES) {
      // Check the current viewport first
      const found = await tryFind(3000);
      if (found) return found;
      // Scroll down incrementally inside AG Grid to reveal virtualised rows
      const prevScrollTop: number = await gridCont.evaluate(
        (el) => el.scrollTop,
      );
      await gridCont.evaluate((el) => {
        el.scrollTop += el.clientHeight;
      });
      await this.page.waitForTimeout(400);
      const newScrollTop: number = await gridCont.evaluate(
        (el) => el.scrollTop,
      );
      const foundAfterScroll = await tryFind(2000);
      if (foundAfterScroll) return foundAfterScroll;
      // If scroll position didn't change we've hit the bottom of this page
      if (newScrollTop === prevScrollTop) {
        // Reset scroll before moving to the next paginated page
        await gridCont.evaluate((el) => {
          el.scrollTop = 0;
        });
        const nextButton = this.nextPageButton();
        // Check disabled via aria-disabled, class, or whether the button is actually enabled
        const ariaDisabled = await nextButton.getAttribute("aria-disabled");
        const classAttr = await nextButton.getAttribute("class");
        const isDisabled =
          ariaDisabled === "true" ||
          classAttr?.includes("ag-disabled") ||
          !(await nextButton.isEnabled());
        if (isDisabled) break;
        await nextButton.click();
        pagesChecked++;
        await this.page.waitForTimeout(500);
      }
    }
    throw new Error(`Row with key "${key}" not found across all pages`);
  }

  /**
   * Delete a document by name.
   * Uses findRowAcrossPages for reliable document location.
   * @param documentName - The name of the document to delete
   * @returns true if deletion was successful, false if document not found
   */
  async deleteDocument(
    documentNames: string | string[],
  ): Promise<boolean | { found: string[]; notFound: string[] }> {
    await this.open();
    // Handle single document case
    if (typeof documentNames === "string") {
      let row: Locator;
      try {
        row = await this.findRowAcrossPages(documentNames);
      } catch {
        return false; // Document not found
      }
      // Select the document (click checkbox)
      const checkbox = this.getRowCheckbox(row);
      await checkbox.click();
      // Click the Delete button
      const deleteBtn = this.deleteButton();
      await expect(deleteBtn).toBeVisible();
      await deleteBtn.click();
      // Confirm deletion in the dialog
      const confirmDialog = this.deleteDocumentDialog();
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      const confirmButton = this.confirmDeleteButton();
      await confirmButton.click();
      // Wait for success message
      await expect(this.deleteSuccessToast()).toBeVisible({ timeout: 10000 });
      // Wait for the success message to disappear
      await this.page.waitForTimeout(1000);
      return true;
    }
    // Handle multiple documents case
    const found: string[] = [];
    const notFound: string[] = [];
    // Find and select all documents that exist
    // findRowAcrossPages now resets to first page at the start automatically
    for (const documentName of documentNames) {
      try {
        const row = await this.findRowAcrossPages(documentName);
        const checkbox = this.getRowCheckbox(row);
        await checkbox.click();
        found.push(documentName);
        await this.page.waitForTimeout(200); // Small delay between selections
      } catch {
        notFound.push(documentName);
      }
    }
    // If no documents were found, return early
    if (found.length === 0) {
      return { found, notFound };
    }
    // Click the Delete button
    const deleteBtn = this.deleteButton();
    await expect(deleteBtn).toBeVisible();
    await deleteBtn.click();
    // Confirm deletion in the dialog
    const confirmDialog = this.deleteDocumentDialog();
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });
    const confirmButton = this.confirmDeleteButton();
    await confirmButton.click();
    // Wait for success message
    await expect(this.deleteSuccessToast()).toBeVisible({ timeout: 10000 });
    // Wait for the success message to disappear
    await this.page.waitForTimeout(1000);
    return { found, notFound };
  }

  /**
   * Open a document by clicking on it.
   * Uses findRowAcrossPages for reliable document location.
   * @param fileName - The name of the document to open
   */
  async openDocument(fileName: string) {
    await this.open();

    // Find the document row using reliable method
    const row = await this.findRowAcrossPages(fileName);

    // Click on the document link
    const fileLink = row.locator("span").filter({ hasText: fileName }).first();

    await expect(fileLink).toBeVisible({ timeout: 10000 });
    await fileLink.click();
  }

  async getFirstChunkText(): Promise<string> {
    await expect(this.page.getByText(/Chunk \d+/i).first()).toBeVisible();

    const chunk = this.page.locator("blockquote").first();
    return (await chunk.textContent()) || "";
  }

  async logFirstChunk(docName: string): Promise<string> {
    await this.openDocument(docName);
    const firstChunk = await this.getFirstChunkText();
    logger.info(`First chunk for "${docName}": ${firstChunk}`);
    return firstChunk;
  }

  /**
   * Verify that a document has 'Active' status.
   * Uses findRowAcrossPages for reliable document location.
   * @param docName - The name of the document to verify
   */
  async verifyDocumentActive(docName: string) {
    await this.open();
    // Use search to filter to the document, then poll its status directly.
    // Keeping the search active while checking status avoids stale-locator issues
    // caused by grid re-renders when search is cleared.
    const searchInp = this.searchInput();

    // Wait for the search input to be visible before entering the polling loop.
    // Without this guard the loop body executes against a not-yet-rendered grid,
    // which causes fill() to silently no-op and row lookups to always return null,
    // burning the entire 2-minute deadline with no progress.
    const searchReady = await searchInp
      .waitFor({ state: "visible", timeout: 15000 })
      .then(() => true)
      .catch(() => false);
    if (!searchReady) {
      throw new Error(
        `Knowledge grid search input not visible — page may not have loaded correctly`,
      );
    }

    const deadline = Date.now() + 300000; // 5 minutes for indexing to complete
    while (Date.now() < deadline) {
      // Filter grid to the target document
      await searchInp.clear();
      await searchInp.fill(docName);
      await this.page.waitForTimeout(800);
      // Try row-id first, fall back to partial source-cell text match
      let row = this.getRowById(docName).first();
      if (!(await row.isVisible().catch(() => false))) {
        const partial = this.getSourceCellByPartialText(docName);
        if (await partial.isVisible().catch(() => false)) {
          row = partial.locator('xpath=ancestor::*[@role="row"][1]');
        }
      }
      const rowVisible = await row.isVisible().catch(() => false);
      if (!rowVisible) {
        logger.info(`  ⏳ Document "${docName}" not yet visible, retrying...`);
        // Refresh the grid before the next poll so newly ingested docs appear
        await searchInp.clear();
        continue;
      }
      // Row is visible — scroll right to reveal the Status column and read it
      await this.grid().evaluate((el) => {
        el.scrollLeft = el.scrollWidth;
      });
      await this.page.waitForTimeout(300);
      const status = this.getStatusCell(row);
      let statusText = (await status.innerText().catch(() => "")) || "";
      if (!statusText) {
        statusText = (await status.textContent().catch(() => "")) || "";
      }
      if (statusText.includes("Animated Processing Icon")) {
        statusText = "Processing";
      }
      if (statusText.toLowerCase().includes("active")) {
        // Clear search before returning
        await searchInp.clear();
        return;
      }
      logger.info(
        `  ⏳ Document "${docName}" status: "${statusText.trim()}", waiting...`,
      );
      await this.page.waitForTimeout(5000);
    }
    await searchInp.clear();
    throw new Error(
      `Document "${docName}" did not reach Active status within the timeout`,
    );
  }

  /**
   * Verify that a document has been removed from the knowledge grid.
   * Searches for the document, and asserts it is NOT visible.
   * Passes immediately when the document is absent; fails if it is still present.
   * @param docName - The name of the document that should no longer exist
   */
  async verifyDocumentDeleted(docName: string): Promise<void> {
    await this.open();
    const searchInp = this.searchInput();
    await searchInp.clear();
    await searchInp.fill(docName);
    await this.page.waitForTimeout(800);
    const row = this.getRowById(docName).first();
    const isPresent = await row.isVisible({ timeout: 5000 }).catch(() => false);
    await searchInp.clear();
    if (isPresent) {
      throw new Error(`Document "${docName}" still exists after deletion`);
    }
    logger.info(`Document "${docName}" successfully deleted`);
  }

  async getDocumentStatus(docName: string): Promise<string> {
    await this.open();
    const row = await this.findRowAcrossPages(docName);
    const status = this.getStatusCell(row).first();
    await expect(status).toBeVisible({ timeout: 30000 });
    let statusText = (await status.innerText().catch(() => "")) || "";
    if (!statusText) {
      statusText = (await status.textContent().catch(() => "")) || "";
    }
    if (statusText.includes("Animated Processing Icon")) {
      statusText = "Processing";
    }
    return statusText.trim();
  }

  /**
   * Clear the search and return to unfiltered document list
   */
  async clearSearch() {
    // Find and click the close button (X) in the search bar
    const closeButton = this.searchInput()
      .locator("..")
      .locator("button")
      .first();
    try {
      await closeButton.click({ timeout: 2000 });
      await this.page.waitForTimeout(1000);
    } catch {
      // If close button not found or not clickable, clear the input manually
      const searchInp = this.searchInput();
      await searchInp.clear();
      await this.page.keyboard.press("Enter");
      await this.page.waitForTimeout(1000);
    }
  }

  /**
   * Search for content and get all matching document names
   * Extracts document names from the row-id attribute
   * @param searchTerm - The term to search for
   * @returns Array of document names that match the search
   */
  async getSearchResults(searchTerm: string): Promise<string[]> {
    await this.open();
    const searchInp = this.searchInput();
    await searchInp.fill(searchTerm);
    await this.page.keyboard.press("Enter");
    // Wait longer for search to complete and results to render
    // Increased from 2000ms to 5000ms to handle slower indexing/search operations
    await this.page.waitForTimeout(5000);
    // Check for search errors that may have occurred during the search operation
    // This is critical as search_phase_execution_exception can happen at any time
    await this.checkForSearchError();
    // Get all data rows with checkboxes (these are the actual document rows, not headers)
    const dataRows = this.getDataRows();
    const count = await dataRows.count();
    const documentNames: string[] = [];
    for (let i = 0; i < count; i++) {
      const row = dataRows.nth(i);
      // Get the row-id attribute which contains the document name
      const rowId = await row.getAttribute("row-id");
      // Filter out empty strings and add to results
      if (rowId && rowId.trim()) {
        documentNames.push(rowId.trim());
      }
    }
    // Clear the search to return to unfiltered state for next operations
    await this.clearSearch();
    return documentNames;
  }

  /**
   * Create a knowledge filter.
   * @param filterName - Name of the filter to create
   * @param sourceFileName - Name of the source file to include in the filter
   */
  async createKnowledgeFilter(filterName: string, sourceFileName: string) {
    // Just navigate to knowledge page directly
    await this.knowledgeLink().click();
    await expect(this.projectKnowledgeHeading()).toBeVisible();
    // Wait for the Knowledge Filters section to be visible
    await expect(this.knowledgeFiltersHeading()).toBeVisible({ timeout: 5000 });
    // Click the + button next to "Knowledge Filters" using the title attribute
    const createFilterBtn = this.createFilterButton();
    await expect(createFilterBtn).toBeVisible({ timeout: 5000 });
    await createFilterBtn.click();
    // Wait for the filter form to appear by checking for the filter name input
    const filterNameInp = this.filterNameInput();
    await expect(filterNameInp).toBeVisible({ timeout: 5000 });
    // Fill in the filter name
    await filterNameInp.fill(filterName);
    await this.page.waitForTimeout(300);
    // Click on the "All sources" button/dropdown in the filter form (right panel)
    const sourcesBtn = this.allSourcesButton();
    await expect(sourcesBtn).toBeVisible({ timeout: 5000 });
    await sourcesBtn.click();
    // Wait for the dropdown menu to appear
    await this.page.waitForTimeout(500);
    // First, deselect "All sources" by clicking on it
    const allSourcesOpt = this.allSourcesOption();
    await expect(allSourcesOpt).toBeVisible({ timeout: 3000 });
    await allSourcesOpt.click();
    await this.page.waitForTimeout(300);
    // Use the search input in the dropdown to find the specific document
    const searchInp = this.searchOptionsInput();
    await expect(searchInp).toBeVisible({ timeout: 3000 });
    await searchInp.fill(sourceFileName);
    // Wait longer for search results to appear (increased from 500ms to 2000ms)
    await this.page.waitForTimeout(2000);
    // Click on the filtered document option with retry logic
    const sourceOption = this.getSourceOption(sourceFileName);
    // Retry mechanism: wait up to 15 seconds for the document to appear in the dropdown
    let retries = 3;
    let found = false;
    while (retries > 0 && !found) {
      try {
        await expect(sourceOption).toBeVisible({ timeout: 5000 });
        found = true;
      } catch {
        retries--;
        if (retries > 0) {
          // Clear and re-enter the search to refresh the dropdown
          await searchInp.clear();
          await this.page.waitForTimeout(500);
          await searchInp.fill(sourceFileName);
          await this.page.waitForTimeout(2000);
        }
      }
    }
    // Final check - if still not found, throw error
    await expect(sourceOption).toBeVisible({ timeout: 5000 });
    await sourceOption.click();
    await this.page.waitForTimeout(500);
    // Close the dropdown by pressing Escape
    await this.page.keyboard.press("Escape");
    await this.page.waitForTimeout(300);
    // Click the "Create Filter" button
    const createButton = this.createFilterSubmitButton();
    await expect(createButton).toBeVisible({ timeout: 5000 });
    await createButton.click();
    // Wait for the filter to be created (form should close)
    await this.page.waitForTimeout(1000);
  }

  /**
   * Delete a knowledge filter by name.
   * @param filterName - Name of the filter to delete
   */
  async deleteKnowledgeFilter(filterName: string) {
    await this.knowledgeLink().click();
    await expect(this.projectKnowledgeHeading()).toBeVisible();
    // Find the filter in the sidebar and click on it to open the form
    const filterItem = this.getFilterItem(filterName);
    try {
      await expect(filterItem).toBeVisible({ timeout: 5000 });
      // Click on the filter to open the edit form
      await filterItem.click();
      // Wait for the "Delete Filter" button to appear (confirms form is open)
      const deleteBtn = this.deleteFilterButton();
      await expect(deleteBtn).toBeVisible({ timeout: 5000 });
      await deleteBtn.click();
      // Wait for the form to close (filter deleted)
      await this.page.waitForTimeout(1000);
    } catch {
      // Filter not found or already deleted
    }
  }

  /**
   * Get all visible chunks in the chunk viewer.
   * @returns Array of chunk texts in order (top to bottom)
   */
  private async getAllChunks(): Promise<string[]> {
    // Get all visible chunk elements (blockquotes contain chunk text)
    const chunks = this.chunkElements();
    await expect(chunks.first()).toBeVisible({ timeout: 5000 });
    const count = await chunks.count();
    const chunkTexts: string[] = [];
    for (let i = 0; i < count; i++) {
      const chunkText = await chunks.nth(i).textContent();
      if (chunkText && chunkText.trim()) {
        chunkTexts.push(chunkText.trim());
      }
    }
    return chunkTexts;
  }

  /**
   * Search for chunks containing a specific token and return top 2 results.
   * @param searchToken - The token to search for in chunks
   * @returns Array containing the top 2 chunk texts after search
   */
  async searchChunks(searchToken: string): Promise<string[]> {
    // Locate the search input in the chunk viewer
    const searchInp = this.searchInput();
    await expect(searchInp).toBeVisible({ timeout: 5000 });
    // Clear any existing search and enter the token
    await searchInp.clear();
    await searchInp.fill(searchToken);
    await this.page.keyboard.press("Enter");
    // Wait for search to complete and chunks to re-rank
    await this.page.waitForTimeout(2000);
    // Get all chunks after search
    const allChunks = await this.getAllChunks();
    // Return only the top 2 chunks
    return allChunks.slice(0, 2);
  }

  // ============================================================================
  // METHODS ADDED FOR AUTOMATED TESTING SUITE
  // ============================================================================

  /**
   * Delete all documents by selecting the master checkbox
   */
  async deleteAllDocuments() {
    // Check if the knowledge base is already empty
    const noKnowledgeMsg = this.page.getByText("No knowledge", { exact: true });
    const isEmpty = await noKnowledgeMsg
      .isVisible({ timeout: 2000 })
      .catch(() => false);

    if (!isEmpty) {
      // If there are files, select the source checkbox to select all files
      const selectAllCheckbox = this.page
        .locator('.ag-header-row input[type="checkbox"]')
        .first();

      if (await selectAllCheckbox.isVisible({ timeout: 2000 })) {
        await selectAllCheckbox.click();
        await this.page.waitForTimeout(1000);

        const deleteBtn = this.page.getByRole("button", { name: "Delete" });
        if (await deleteBtn.isEnabled()) {
          await deleteBtn.click();
          await this.page.waitForTimeout(1000);

          // Confirm deletion
          const confirmBtn = this.page
            .getByRole("button", { name: "Delete" })
            .last();
          await confirmBtn.click();

          // Wait for the 'No knowledge' empty state to appear
          await expect(noKnowledgeMsg).toBeVisible({ timeout: 10000 });
        }
      }
    }
  }

  /**
   * Start a file upload process without waiting for it to complete.
   * Useful for negative test cases like testing upload cancellation.
   */
  async ingestFileNonBlocking(filePath: string) {
    await this.open();
    await this.addKnowledgeButton().click();
    await this.fileInput().setInputFiles(filePath);

    try {
      const overwriteBtn = this.overwriteButton();
      await overwriteBtn.waitFor({ state: "visible", timeout: 3000 });
      await expect(overwriteBtn).toBeEnabled({ timeout: 3000 });
      await overwriteBtn.click();
    } catch {
      // No overwrite button appeared
    }

    await this.page.keyboard.press("Escape");
    await this.page.waitForTimeout(500);
  }
}
