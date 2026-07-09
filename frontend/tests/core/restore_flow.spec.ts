import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

test.describe("Restore Flow", () => {
  // Skip test for SaaS environments (only run on OSS/localhost)
  const baseUrl = process.env.BASE_URL || "http://localhost:3000";
  const isSaaS = !baseUrl.includes("localhost");
  test.skip(
    isSaaS,
    "Picture description feature is disabled for SaaS environments",
  );

  test.beforeEach(async ({ page, settings }) => {
    // Make sure we start with a clean default state
    await navigateToHome(page);
    await settings.open();
    await settings.clickTab("Langflow");

    const pictureDescToggle = page.getByRole("switch", {
      name: /picture descriptions/i,
    });
    const tableStructureToggle = page.getByRole("switch", {
      name: /table structure/i,
    });
    const chunkSizeInput = page.getByLabel(/chunk size/i);
    const chunkOverlapInput = page.getByLabel(/chunk overlap/i);

    const pictureDescState = await pictureDescToggle.getAttribute("data-state");
    const tableStructureState =
      await tableStructureToggle.getAttribute("data-state");
    const chunkSize = await chunkSizeInput.inputValue();
    const chunkOverlap = await chunkOverlapInput.inputValue();

    if (
      pictureDescState === "checked" ||
      tableStructureState !== "checked" ||
      chunkSize !== "1000" ||
      chunkOverlap !== "200"
    ) {
      logger.info(
        "\n🔧 Non-default settings detected during setup, restoring defaults...",
      );
      const restoreFlowButton = page
        .locator("text=Knowledge Ingest")
        .locator("..")
        .getByRole("button", { name: /restore flow/i });
      await restoreFlowButton.scrollIntoViewIfNeeded();
      await restoreFlowButton.click();

      const dialog = page.locator("text=Restore default Ingest flow");
      await expect(dialog).toBeVisible({ timeout: 5000 });
      const restoreButton = page.getByRole("button", { name: /^restore$/i });

      await restoreButton.click();
      await expect(dialog).not.toBeVisible({ timeout: 30000 });

      await settings.saveIngestSettings();
      await page.waitForTimeout(1500);
    }
  });

  test("should restore default settings after making changes @33219238", async ({
    page,
    settings,
  }) => {
    test.setTimeout(120000);

    // Define the expected default state
    const DEFAULT_STATE = {
      pictureDescriptions: false,
      tableStructure: true,
      chunkSize: "1000",
      chunkOverlap: "200",
    };

    // Navigate to the application
    await navigateToHome(page);
    await settings.open();
    await settings.clickTab("Langflow");

    // Get references to settings elements
    const pictureDescToggle = page.getByRole("switch", {
      name: /picture descriptions/i,
    });
    const tableStructureToggle = page.getByRole("switch", {
      name: /table structure/i,
    });
    const chunkSizeInput = page.getByLabel(/chunk size/i);
    const chunkOverlapInput = page.getByLabel(/chunk overlap/i);

    // Make changes to settings
    logger.info("\n🔧 Making changes to settings...");
    await settings.setPictureDescriptions(true);
    await page.waitForTimeout(1000);

    await settings.setTableStructure(false);
    await page.waitForTimeout(1000);

    await settings.updateChunkSettings("500", "50");
    await page.waitForTimeout(1000);
    logger.info("  ✓ Settings changed");

    // Verify changes were applied
    await page.waitForTimeout(500);
    await settings.open();

    await pictureDescToggle.scrollIntoViewIfNeeded();
    const pictureDescStateAfterChange =
      await pictureDescToggle.getAttribute("data-state");
    const pictureDescAfterChange = pictureDescStateAfterChange === "checked";

    await tableStructureToggle.scrollIntoViewIfNeeded();
    const tableStructureStateAfterChange =
      await tableStructureToggle.getAttribute("data-state");
    const tableStructureAfterChange =
      tableStructureStateAfterChange === "checked";

    await chunkSizeInput.scrollIntoViewIfNeeded();
    const chunkSizeAfterChange = await chunkSizeInput.inputValue();

    await chunkOverlapInput.scrollIntoViewIfNeeded();
    const chunkOverlapAfterChange = await chunkOverlapInput.inputValue();

    expect(pictureDescAfterChange).toBe(true);
    expect(tableStructureAfterChange).toBe(false);
    expect(chunkSizeAfterChange).toBe("500");
    expect(chunkOverlapAfterChange).toBe("50");

    // Click on "Restore flow" button
    logger.info("\n🔄 Restoring default settings...");
    await page.waitForTimeout(500);
    const restoreFlowButton = page
      .locator("text=Knowledge Ingest")
      .locator("..")
      .getByRole("button", { name: /restore flow/i });
    await restoreFlowButton.scrollIntoViewIfNeeded();
    await expect(restoreFlowButton).toBeVisible();
    await restoreFlowButton.click();

    // Verify and confirm restore dialog
    const dialog = page.locator("text=Restore default Ingest flow");
    await expect(dialog).toBeVisible({ timeout: 5000 });

    const dialogText = page.getByText(
      /this restores defaults and discards all custom settings/i,
    );
    await expect(dialogText).toBeVisible();
    await page.waitForTimeout(500);

    const restoreButton = page.getByRole("button", { name: /^restore$/i });
    await expect(restoreButton).toBeVisible();
    await page.waitForTimeout(300);
    await restoreButton.click();

    // Wait for dialog to close and restore to complete
    await expect(dialog).not.toBeVisible({ timeout: 30000 });
    await page.waitForTimeout(1000);

    // Save the restored default settings
    await page.waitForTimeout(500);
    await settings.saveIngestSettings();
    await page.waitForTimeout(1500);
    logger.info("  ✓ Settings restored and saved");

    // Wait for UI to update with restored values
    await chunkSizeInput.scrollIntoViewIfNeeded();
    await expect(async () => {
      const currentChunkSize = await chunkSizeInput.inputValue();
      expect(currentChunkSize).toBe(DEFAULT_STATE.chunkSize);
    }).toPass({ timeout: 10000 });

    // Validate settings are back to default state
    logger.info("\n🔍 Validating restored defaults...");

    await pictureDescToggle.scrollIntoViewIfNeeded();
    const restoredPictureDescState =
      await pictureDescToggle.getAttribute("data-state");
    const restoredPictureDesc = restoredPictureDescState === "checked";

    await tableStructureToggle.scrollIntoViewIfNeeded();
    const restoredTableStructureState =
      await tableStructureToggle.getAttribute("data-state");
    const restoredTableStructure = restoredTableStructureState === "checked";

    await chunkSizeInput.scrollIntoViewIfNeeded();
    const restoredChunkSize = await chunkSizeInput.inputValue();

    await chunkOverlapInput.scrollIntoViewIfNeeded();
    const restoredChunkOverlap = await chunkOverlapInput.inputValue();

    // Assert all settings match the expected default values
    expect(restoredPictureDesc).toBe(DEFAULT_STATE.pictureDescriptions);
    expect(restoredTableStructure).toBe(DEFAULT_STATE.tableStructure);
    expect(restoredChunkSize).toBe(DEFAULT_STATE.chunkSize);
    expect(restoredChunkOverlap).toBe(DEFAULT_STATE.chunkOverlap);

    logger.info(
      "  ✓ All settings restored to defaults (Picture Descriptions: OFF, Table Structure: OFF, Chunk Size: 1000, Chunk Overlap: 200)",
    );
  });

  test("should maintain default settings when restore is clicked on already default state @34581649", async ({
    page,
    settings,
  }) => {
    test.setTimeout(120000);

    // Define the expected default state
    const DEFAULT_STATE = {
      pictureDescriptions: false,
      tableStructure: true,
      chunkSize: "1000",
      chunkOverlap: "200",
    };

    // Navigate to the application
    await navigateToHome(page);
    await settings.open();
    await settings.clickTab("Langflow");

    // Get references to settings elements
    const pictureDescToggle = page.getByRole("switch", {
      name: /picture descriptions/i,
    });
    const tableStructureToggle = page.getByRole("switch", {
      name: /table structure/i,
    });
    const chunkSizeInput = page.getByLabel(/chunk size/i);
    const chunkOverlapInput = page.getByLabel(/chunk overlap/i);

    // Verify settings are already in default state (from previous test)
    logger.info("\n🔍 Verifying settings are in default state...");
    await page.waitForTimeout(500);

    await pictureDescToggle.scrollIntoViewIfNeeded();
    const initialPictureDescState =
      await pictureDescToggle.getAttribute("data-state");
    const initialPictureDesc = initialPictureDescState === "checked";

    await tableStructureToggle.scrollIntoViewIfNeeded();
    const initialTableStructureState =
      await tableStructureToggle.getAttribute("data-state");
    const initialTableStructure = initialTableStructureState === "checked";

    await chunkSizeInput.scrollIntoViewIfNeeded();
    const initialChunkSize = await chunkSizeInput.inputValue();

    await chunkOverlapInput.scrollIntoViewIfNeeded();
    const initialChunkOverlap = await chunkOverlapInput.inputValue();

    // Assert settings are in default state
    expect(initialPictureDesc).toBe(DEFAULT_STATE.pictureDescriptions);
    expect(initialTableStructure).toBe(DEFAULT_STATE.tableStructure);
    expect(initialChunkSize).toBe(DEFAULT_STATE.chunkSize);
    expect(initialChunkOverlap).toBe(DEFAULT_STATE.chunkOverlap);
    logger.info("  ✓ Settings confirmed to be in default state");

    // Click on "Restore flow" button even though settings are already default
    logger.info("\n🔄 Clicking restore on already default settings...");
    await page.waitForTimeout(500);
    const restoreFlowButton = page
      .locator("text=Knowledge Ingest")
      .locator("..")
      .getByRole("button", { name: /restore flow/i });
    await restoreFlowButton.scrollIntoViewIfNeeded();
    await expect(restoreFlowButton).toBeVisible();
    await restoreFlowButton.click();

    // Verify and confirm restore dialog
    const dialog = page.locator("text=Restore default Ingest flow");
    await expect(dialog).toBeVisible({ timeout: 5000 });

    const dialogText = page.getByText(
      /this restores defaults and discards all custom settings/i,
    );
    await expect(dialogText).toBeVisible();
    await page.waitForTimeout(500);

    const restoreButton = page.getByRole("button", { name: /^restore$/i });
    await expect(restoreButton).toBeVisible();
    await page.waitForTimeout(300);
    await restoreButton.click();

    // Wait for dialog to close and restore to complete
    await expect(dialog).not.toBeVisible({ timeout: 30000 });
    await page.waitForTimeout(1000);

    // Save the settings
    await page.waitForTimeout(500);

    logger.info("  ✓ Restore completed and settings saved");

    // Wait for UI to update
    await chunkSizeInput.scrollIntoViewIfNeeded();
    await expect(async () => {
      const currentChunkSize = await chunkSizeInput.inputValue();
      expect(currentChunkSize).toBe(DEFAULT_STATE.chunkSize);
    }).toPass({ timeout: 10000 });

    // Validate settings remain in default state
    logger.info("\n🔍 Validating settings remain in default state...");

    await pictureDescToggle.scrollIntoViewIfNeeded();
    const finalPictureDescState =
      await pictureDescToggle.getAttribute("data-state");
    const finalPictureDesc = finalPictureDescState === "checked";

    await tableStructureToggle.scrollIntoViewIfNeeded();
    const finalTableStructureState =
      await tableStructureToggle.getAttribute("data-state");
    const finalTableStructure = finalTableStructureState === "checked";

    await chunkSizeInput.scrollIntoViewIfNeeded();
    const finalChunkSize = await chunkSizeInput.inputValue();

    await chunkOverlapInput.scrollIntoViewIfNeeded();
    const finalChunkOverlap = await chunkOverlapInput.inputValue();

    // Assert all settings still match the expected default values
    expect(finalPictureDesc).toBe(DEFAULT_STATE.pictureDescriptions);
    expect(finalTableStructure).toBe(DEFAULT_STATE.tableStructure);
    expect(finalChunkSize).toBe(DEFAULT_STATE.chunkSize);
    expect(finalChunkOverlap).toBe(DEFAULT_STATE.chunkOverlap);

    logger.info(
      "  ✓ All settings remain in default state after restore (Picture Descriptions: OFF, Table Structure: OFF, Chunk Size: 1000, Chunk Overlap: 200)",
    );
  });
});
