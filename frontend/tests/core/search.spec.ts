import path from "path";
import { OPENAI_CONFIG } from "../config/provider";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

const TEST_DOCUMENT = "OpenRAG.Index.Test.Document.txt";
const TEST_DOCUMENT_PATH = path.join(__dirname, "../test-data", TEST_DOCUMENT);
const UNIQUE_SEARCH_TOKEN = "OPENSEARCH-7419-ZX";

test("Opensearch Indexing - OpenAI @33219220", async ({
  page,
  settings,
  knowledge,
  cleanupDocuments,
}) => {
  test.setTimeout(180000);

  // Navigate to the application
  await navigateToHome(page);

  logger.info(`\n🧪 Testing Opensearch Indexing with OpenAI`);

  logger.info(`  🧹 Cleaning up existing test document...`);
  try {
    await knowledge.deleteDocument(TEST_DOCUMENT);
    logger.info(`  ✓ Test document cleaned up`);
  } catch (_error) {
    logger.info(`  ℹ️  No existing test document to clean up`);
  }

  // Step 2: Set embedding model for OpenAI
  logger.info(`  ⚙️  Setting embedding model for OpenAI...`);
  await settings.clickTab("Langflow");
  await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);
  logger.info(`  ✓ Embedding model set to: ${OPENAI_CONFIG.embedding}`);

  // Step 3: Ingest the test document
  logger.info(`  📄 Ingesting test document...`);
  const ingestedFileName = await knowledge.ingestFile(TEST_DOCUMENT_PATH);
  logger.info(`  ✓ Document ingested: ${ingestedFileName}`);

  // Register for cleanup
  await cleanupDocuments([TEST_DOCUMENT]);

  // Step 4: Wait for document to be indexed (Active status)
  logger.info(`  ⏳ Waiting for document to be indexed...`);
  await knowledge.verifyDocumentActive(TEST_DOCUMENT);
  logger.info(`  ✓ Document is indexed and active`);

  // Step 5: Search for the unique token
  // Note: Search works for content within documents, not document names
  logger.info(`  🔍 Searching for unique token: ${UNIQUE_SEARCH_TOKEN}`);
  const searchResults = await knowledge.getSearchResults(UNIQUE_SEARCH_TOKEN);

  logger.info(`  📊 Search results: ${searchResults.length} document(s) found`);
  searchResults.forEach((doc, index) => {
    logger.info(`     ${index + 1}. ${doc}`);
  });

  // Step 6: Verify results
  // The test document must be in the results (other documents may also appear)
  const targetDocumentFound = searchResults.includes(TEST_DOCUMENT);

  if (!targetDocumentFound) {
    throw new Error(
      `❌ FAILED: Test document "${TEST_DOCUMENT}" not found in search results for token "${UNIQUE_SEARCH_TOKEN}"\n` +
        `   Search returned ${searchResults.length} document(s): ${searchResults.join(", ")}\n` +
        `   This means the document was not properly indexed or the search functionality is not working.`,
    );
  }

  // Success!
  if (searchResults.length === 1) {
    logger.info(`  ✅ SUCCESS: "${TEST_DOCUMENT}" found as the only result`);
  } else {
    const otherDocs = searchResults.filter((doc) => doc !== TEST_DOCUMENT);
    logger.info(`  ✅ SUCCESS: "${TEST_DOCUMENT}" found in results`);
    logger.info(
      `     ℹ️  Also found ${otherDocs.length} other document(s): ${otherDocs.join(", ")}`,
    );
  }
  logger.info(`  ✓ Opensearch indexing verified for OpenAI\n`);

  // Assertions for Playwright reporting
  expect(targetDocumentFound).toBe(true);
  expect(searchResults).toContain(TEST_DOCUMENT);
});
