import * as fs from "fs";
import * as path from "path";
import { TEST_CONFIG } from "../config/test.config";
import { expect, test } from "../utils/fixtures";
import { navigateToKnowledge } from "../utils/navigation";

test.describe("Diverse Format Ingestion. @33219208 , @34581152 , @34581153 , @34581154", () => {
  test("@smoke Upload folder with diverse file formats and verify all are Active", async ({
    page,
    knowledge,
  }) => {
    await navigateToKnowledge(page);
    // Set a generous timeout for the whole test
    test.setTimeout(300000); // 5 minutes

    // Page is already navigated to /knowledge by the fixture

    // Get the absolute path to the sample files folder
    const folderPath = path.resolve(TEST_CONFIG.documents.allSampleFiles.path);

    // Verify the folder exists
    if (!fs.existsSync(folderPath)) {
      throw new Error(`Folder not found: ${folderPath}`);
    }

    // Get list of files in the folder that match supported formats
    const allFiles = fs.readdirSync(folderPath);
    const supportedFiles = allFiles.filter((file) => {
      const ext = path.extname(file).toLowerCase().replace(".", "");
      return TEST_CONFIG.supportedFormats.includes(ext);
    });

    // Step 1: Upload all files first (without verifying status yet)
    const uploadedFiles: string[] = [];

    for (const fileName of supportedFiles) {
      try {
        const filePath = path.join(folderPath, fileName);
        const uploadedFileName = await knowledge.ingestFile(filePath);
        uploadedFiles.push(uploadedFileName);
      } catch (error) {
        throw new Error(`Failed to upload ${fileName}: ${error}`);
      }
    }

    // Step 2: After all uploads complete, verify each file's status becomes Active
    for (const uploadedFileName of uploadedFiles) {
      try {
        await knowledge.verifyDocumentActive(uploadedFileName);
      } catch (error) {
        throw new Error(`Failed to verify ${uploadedFileName}: ${error}`);
      }
    }

    // Verify all files were uploaded successfully
    expect(uploadedFiles.length).toBe(supportedFiles.length);
  });

  // test('Negative testcase for mismatch file extension', async ({ knowledge, settings, page }) => {
  //   await navigateToKnowledge(page);
  //   test.setTimeout(300000);

  //   const humanHeartPath = path.resolve('test-data/human_heart.pdf');
  //   const heartPath = path.resolve('test-data/heart.pdf');

  //   if (!fs.existsSync(humanHeartPath)) {
  //     throw new Error(`File not found: ${humanHeartPath}`);
  //   }

  //   if (!fs.existsSync(heartPath)) {
  //     throw new Error(`File not found: ${heartPath}`);
  //   }

  //   await settings.setPictureDescriptions(true);
  //   await settings.setOCR(true);

  //   const uploadedHumanHeart = await knowledge.ingestFile(humanHeartPath);
  //   const uploadedHeart = await knowledge.ingestFile(heartPath);

  //   await knowledge.open();
  //   await knowledge.fetchLatestDocs();

  //   const uploadedFiles = [uploadedHumanHeart, uploadedHeart];

  //   for (const uploadedFileName of uploadedFiles) {
  //     const row = await knowledge.findRowAcrossPages(uploadedFileName);
  //     const status = row.locator('[col-id="status"]');
  //     const statusText = ((await status.textContent()) || '').trim();

  //     expect(['Active', 'Failed']).toContain(statusText);
  //     console.log(`Document "${uploadedFileName}" status: ${statusText}`);

  //     await knowledge.openDocument(uploadedFileName);
  //     const firstChunk = await knowledge.getFirstChunkText();
  //     console.log(`First chunk of "${uploadedFileName}": ${firstChunk}`);
  //     expect(firstChunk.trim().length).toBeGreaterThan(0);

  //     await knowledge.open();
  //     await knowledge.fetchLatestDocs();
  //   }
  // });

  test("Verify supported file formats list", async ({ page }) => {
    await navigateToKnowledge(page);
    // This test verifies that all required formats are in the config
    const requiredFormats = [
      "txt",
      "md",
      "html",
      "htm",
      "adoc",
      "asciidoc",
      "asc",
      "pdf",
      "docx",
    ];

    requiredFormats.forEach((format) => {
      expect(TEST_CONFIG.supportedFormats).toContain(format);
    });
  });
});
