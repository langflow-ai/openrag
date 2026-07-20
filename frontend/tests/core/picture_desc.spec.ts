import * as path from "path";
import { OPENAI_CONFIG } from "../config/provider";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

//This feature is disabled for SaaS

test("Picture Description Configuration @33219221", async ({
  page,
  settings,
  knowledge,
  cleanupDocuments,
}) => {
  // Skip test for SaaS environments (only run on OSS/localhost)
  const baseUrl = process.env.BASE_URL || "http://localhost:3000";
  const isSaaS = !baseUrl.includes("localhost");
  test.skip(
    isSaaS,
    "Picture description feature is disabled for SaaS environments",
  );

  test.setTimeout(600000);

  const testDocuments = ["cat1.pdf", "cat2.pdf"];

  // Navigate to the application
  await navigateToHome(page);

  // Set OpenAI models before starting
  logger.info("\n⚙️  Configuring OpenAI models...");
  await settings.clickTab("Langflow");
  await settings.selectModel("Language model", OPENAI_CONFIG.language);
  await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);
  logger.info(`  ✓ Language model: ${OPENAI_CONFIG.language}`);
  logger.info(`  ✓ Embedding model: ${OPENAI_CONFIG.embedding}`);

  // Precondition: Delete any existing test documents
  logger.info("\n🧹 Cleaning up existing test documents...");
  for (const docName of testDocuments) {
    const deleted = await knowledge.deleteDocument(docName);
    if (deleted) {
      logger.info(`  ✓ Removed: "${docName}"`);
    } else {
      logger.info(`  ✓ Not found: "${docName}" (already clean)`);
    }
  }

  // Register documents for automatic cleanup after test
  await cleanupDocuments(testDocuments);

  // Enable picture descriptions
  logger.info("\n📸 Enabling picture descriptions...");
  await settings.clickTab("Langflow");
  await settings.setPictureDescriptions(true);

  // Ingest first PDF with picture descriptions enabled
  logger.info("📄 Ingesting cat1.pdf with picture descriptions ON...");
  const fileName = await knowledge.ingestFile(
    path.join(__dirname, "../test-data/cat1.pdf"),
  );

  // Wait for document to be fully processed and active
  await knowledge.verifyDocumentActive(fileName);

  await knowledge.openDocument(fileName);

  const chunkText = await knowledge.getFirstChunkText();

  // Verify picture description is present
  expect(chunkText).toMatch(/image/i);
  expect(chunkText).toContain("<!-- image -->");
  expect(chunkText.length).toBeGreaterThan(20);
  logger.info("✅ Picture description found in chunks");

  // Disable picture descriptions
  logger.info("\n📸 Disabling picture descriptions...");
  await settings.clickTab("Langflow");
  await settings.setPictureDescriptions(false);

  // Ingest second PDF with picture descriptions disabled
  logger.info("📄 Ingesting cat2.pdf with picture descriptions OFF...");
  const fileName2 = await knowledge.ingestFile(
    path.join(__dirname, "../test-data/cat2.pdf"),
  );

  // Wait for document to be fully processed and active
  await knowledge.verifyDocumentActive(fileName2);

  await knowledge.openDocument(fileName2);

  const chunkText2 = await knowledge.getFirstChunkText();
  // Verify only placeholder is present (no description)
  expect(chunkText2.trim()).toBe("<!-- image -->");
  logger.info("✅ Only placeholder found (no description)");
});
