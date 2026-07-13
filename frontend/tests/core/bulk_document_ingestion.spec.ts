import * as fs from "fs";
import * as path from "path";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

/**
 * Bulk Document Ingestion Test Suite
 * Tests the ability to ingest multiple documents from a folder at once
 *
 * Test: Upload 5 files from bulk_doc_test folder
 * - Clears any existing files from the folder if they exist in KB
 * - Uploads entire folder using the "Folder" option
 * - Waits for "Task completed" with "5 files uploaded successfully" message
 * - Timeout: 2 minutes for bulk upload processing
 *
 */

test.describe("Bulk Document Ingestion @33219230", () => {
  test("@smoke Upload folder with 5 documents and verify successful ingestion", async ({
    page,
    knowledge,
    cleanupDocuments,
  }) => {
    // Set timeout to 6 minutes to accommodate bulk upload processing
    test.setTimeout(360000);

    // Navigate to the application
    await navigateToHome(page);

    // Get the absolute path to the bulk_doc_test folder
    const folderPath = path.resolve(__dirname, "../test-data/bulk_doc_test");

    // Verify the folder exists
    if (!fs.existsSync(folderPath)) {
      throw new Error(`Folder not found: ${folderPath}`);
    }

    // Get list of all files in the folder (excluding hidden files like .DS_Store)
    const allFiles = fs.readdirSync(folderPath);
    const files = allFiles.filter((file: string) => !file.startsWith("."));
    const fileCount = files.length;

    logger.info(`\n📦 Bulk Document Ingestion Test`);
    logger.info(`  📁 Folder: bulk_doc_test`);
    logger.info(`  📄 Files found: ${fileCount} (excluding hidden files)`);

    // Verify we have exactly 5 files
    expect(fileCount).toBe(5);

    // Step 1: Clear all files from the folder if they exist in the KB
    logger.info(`\n  🧹 Cleaning up existing files from knowledge base...`);

    const deleteResult = await knowledge.deleteDocument(files);

    if (typeof deleteResult === "object") {
      logger.info(`     ✓ Deleted: ${deleteResult.found.length} file(s)`);
      logger.info(`     ℹ️  Not found: ${deleteResult.notFound.length} file(s)`);

      // Verify deleted files are actually gone
      if (deleteResult.found.length > 0) {
        logger.info(`\n  🔍 Verifying deleted files are gone...`);
        await knowledge.open();

        for (const fileName of deleteResult.found) {
          try {
            await knowledge.findRowAcrossPages(fileName);
            throw new Error(`File ${fileName} still exists after deletion!`);
          } catch (error) {
            if (
              error instanceof Error &&
              error.message.includes("not found across all pages")
            ) {
              logger.info(`     ✓ Confirmed deleted: ${fileName}`);
            } else {
              throw error;
            }
          }
        }
      }
    }

    // Register files for cleanup after test (use ingested names)
    await cleanupDocuments(files);

    // Step 2: Ingest the entire folder
    logger.info(`\n  📤 Ingesting bulk folder (5 files)...`);
    logger.info(`     ⏳ This may take 1.5-2 minutes...`);

    const folderName = await knowledge.ingestFolder(
      folderPath,
      5,
      120000, // 2 minutes timeout as specified
    );

    logger.info(`  ✓ Bulk ingestion completed: ${folderName}`);

    // Step 3: Verify all files are active (using ingested names)
    logger.info(`\n  🔍 Verifying all files are active...`);
    await knowledge.open();

    let activeCount = 0;
    const failedFiles: string[] = [];

    for (const fileName of files) {
      try {
        await knowledge.verifyDocumentActive(fileName);
        activeCount++;
      } catch (_error) {
        logger.error(`     ✗ File not active: ${fileName}`);
        failedFiles.push(fileName);
      }
    }

    logger.info(`     ✓ Active files: ${activeCount}/${files.length}`);

    // Final verification
    if (failedFiles.length > 0) {
      throw new Error(
        `❌ FAILED: ${failedFiles.length} file(s) not active:\n` +
          `   ${failedFiles.join("\n   ")}`,
      );
    }

    expect(activeCount).toBe(5);
    logger.info(
      `\n  ✅ SUCCESS: All ${activeCount} files successfully ingested and active\n`,
    );
  });

  test("NEGATIVE TEST: Upload combo folder with supported and unsupported documents", async ({
    page,
    knowledge,
    cleanupDocuments,
  }) => {
    // Set timeout to 6 minutes to accommodate bulk upload processing
    test.setTimeout(360000);

    // Navigate to the application
    await navigateToHome(page);

    // Get the absolute path to the combo folder
    const folderPath = path.resolve(__dirname, "../test-data/combo");

    // Verify the folder exists
    if (!fs.existsSync(folderPath)) {
      throw new Error(`Folder not found: ${folderPath}`);
    }

    // Get list of all files in the folder (excluding hidden files like .DS_Store)
    const allFiles = fs.readdirSync(folderPath);
    const files = allFiles.filter((file: string) => !file.startsWith("."));
    const totalFileCount = files.length;

    // Identify supported files
    const supportedFiles = files.filter((file) => file.endsWith(".txt"));
    const unsupportedFiles = files.filter((file) => !file.endsWith(".txt"));
    const expectedSuccessCount = supportedFiles.length;
    const expectedSkippedCount = unsupportedFiles.length;

    logger.info(`\n🧪 NEGATIVE TEST: Combo Folder with Mixed File Types`);
    logger.info(`  📁 Folder: combo`);
    logger.info(`  📄 Total files: ${totalFileCount}`);
    logger.info(`  ✅ Supported: ${expectedSuccessCount} (.txt files)`);
    logger.info(`  ❌ Unsupported: ${expectedSkippedCount} (.ppt files)`);

    // Verify we have the expected file counts
    expect(totalFileCount).toBe(4); // 3 .txt + 1 .ppt
    expect(expectedSuccessCount).toBe(3); // Only 3 .txt files should succeed

    // Step 1: Clear existing files from knowledge base
    logger.info(`\n  🧹 Cleaning up existing files...`);

    const deleteResult = await knowledge.deleteDocument(supportedFiles);

    if (typeof deleteResult === "object") {
      logger.info(
        `     ✓ Deleted: ${deleteResult.found.length}, Not found: ${deleteResult.notFound.length}`,
      );

      // Verify deleted files are actually gone
      if (deleteResult.found.length > 0) {
        await knowledge.open();

        for (const fileName of deleteResult.found) {
          try {
            await knowledge.findRowAcrossPages(fileName);
            throw new Error(`File ${fileName} still exists after deletion!`);
          } catch (error) {
            if (
              error instanceof Error &&
              error.message.includes("not found across all pages")
            ) {
              logger.info(`     ✓ Confirmed: ${fileName}`);
            } else {
              throw error;
            }
          }
        }
      }
    }

    // Register files for cleanup after test
    await cleanupDocuments(supportedFiles);

    // Step 2: Upload combo folder
    logger.info(
      `\n  📤 Uploading combo folder (${expectedSuccessCount} supported + ${expectedSkippedCount} unsupported)...`,
    );

    await knowledge.open();
    await knowledge.addKnowledgeButton().click();

    const [fileChooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page.getByText("Folder").click(),
    ]);

    await fileChooser.setFiles(folderPath);

    // Step 3: Verify immediate toast message
    logger.info(`\n  ✓ Verifying immediate toast message...`);

    const immediateToast = page.getByText(
      `Successfully processed ${expectedSuccessCount} file(s), skipped ${expectedSkippedCount} unsupported`,
    );
    await expect(immediateToast).toBeVisible({ timeout: 10000 });

    logger.info(
      `    Toast: "Successfully processed ${expectedSuccessCount} file(s), skipped ${expectedSkippedCount} unsupported"`,
    );

    // Step 4: Wait for task completion
    logger.info(`\n  ✓ Waiting for ingestion to complete (up to 2 minutes)...`);

    const taskCompletedMessage = page.getByText(
      `${expectedSuccessCount} files uploaded successfully`,
    );
    await expect(taskCompletedMessage).toBeVisible({ timeout: 120000 });

    logger.info(
      `    Task completed: ${expectedSuccessCount} files uploaded successfully`,
    );

    await page.keyboard.press("Escape");

    // Step 5: Verify all files are active
    logger.info(
      `\n  ✓ Verifying all ${expectedSuccessCount} files are active...`,
    );
    await knowledge.open();

    let activeCount = 0;
    const failedFiles: string[] = [];

    for (const fileName of supportedFiles) {
      try {
        await knowledge.verifyDocumentActive(fileName);
        activeCount++;
      } catch (_error) {
        logger.error(`    ✗ File not active: ${fileName}`);
        failedFiles.push(fileName);
      }
    }

    // Final verification
    if (failedFiles.length > 0) {
      throw new Error(
        `❌ ${failedFiles.length} file(s) not active:\n` +
          `   ${failedFiles.join("\n   ")}`,
      );
    }

    expect(activeCount).toBe(expectedSuccessCount);
    logger.info(`    Active files: ${activeCount}/${expectedSuccessCount}`);

    logger.info(`\n  ✅ SUCCESS: Negative test passed`);
    logger.info(`    - Immediate toast showed processed/skipped counts`);
    logger.info(`    - Task completed with ${expectedSuccessCount} files`);
    logger.info(`    - All ${expectedSuccessCount} supported files are active`);
    logger.info(`    - Unsupported .ppt file was correctly skipped\n`);
  });

  test("NEGATIVE TEST: Upload folder with only unsupported documents", async ({
    page,
    knowledge,
  }) => {
    // Set timeout to 2 minutes (no ingestion will happen, just validation)
    test.setTimeout(120000);

    // Navigate to the application
    await navigateToHome(page);

    // Get the absolute path to the uns folder
    const folderPath = path.resolve(__dirname, "../test-data/uns");

    // Verify the folder exists
    if (!fs.existsSync(folderPath)) {
      throw new Error(`Folder not found: ${folderPath}`);
    }

    // Get list of all files in the folder (excluding hidden files)
    const allFiles = fs.readdirSync(folderPath);
    const files = allFiles.filter((file: string) => !file.startsWith("."));
    const totalFileCount = files.length;

    logger.info(`\n🧪 NEGATIVE TEST: Folder with Only Unsupported Documents`);
    logger.info(`  📁 Folder: uns`);
    logger.info(`  📄 Total files: ${totalFileCount}`);
    logger.info(`  ❌ All unsupported: ${files.join(", ")}`);

    // Verify we have exactly 3 unsupported files
    expect(totalFileCount).toBe(3); // sample.ppt + file-sample_1MB.doc + sample.rtf

    // Upload the uns folder
    logger.info(`\n  📤 Uploading folder with only unsupported files...`);

    await knowledge.open();
    await knowledge.addKnowledgeButton().click();

    const [fileChooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page.getByText("Folder").click(),
    ]);

    await fileChooser.setFiles(folderPath);

    // Verify "No supported files found" error message
    logger.info(`\n  ✓ Verifying error message...`);

    const errorMessage = page.getByText("No supported files found");
    await expect(errorMessage).toBeVisible({ timeout: 10000 });

    logger.info(`    Error: "No supported files found"`);

    // Verify the detailed message about supported file types
    const detailedMessage = page.getByText(
      /Please select a folder containing supported document files/i,
    );
    await expect(detailedMessage).toBeVisible({ timeout: 5000 });

    logger.info(`    Details: Prompt to select folder with supported files`);

    await page.keyboard.press("Escape");

    logger.info(`\n  ✅ SUCCESS: Negative test passed`);
    logger.info(
      `    - System correctly rejected folder with only unsupported files`,
    );
    logger.info(`    - Error message displayed: "No supported files found"`);
    logger.info(`    - No documents were ingested\n`);
  });
});
