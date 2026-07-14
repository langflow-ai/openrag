import path from "path";
import { OPENAI_CONFIG } from "../config/provider";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

const TEST_DOCUMENT = "test_chunk_search.pdf";
const TEST_DOCUMENT_PATH = path.join(__dirname, "../test-data", TEST_DOCUMENT);

// Test tokens from the document
const TEST_TOKENS = [
  "RAG-TEST-ALPHA-001",
  "RAG-TEST-BETA-002",
  "RAG-TEST-GAMMA-003",
  "RAG-TEST-DELTA-004",
  "RAG-TEST-EPSILON-005",
  "RAG-TEST-ZETA-006",
  "RAG-TEST-ETA-007",
  "RAG-TEST-THETA-008",
  "RAG-TEST-IOTA-009",
  "RAG-TEST-KAPPA-010",
];

test("Chunk Search & Ranking - OpenAI @33219236", async ({
  page,
  settings,
  knowledge,
  cleanupDocuments,
}) => {
  test.setTimeout(320000);

  // Navigate to the application
  await navigateToHome(page);

  logger.info(`\n🧪 Testing Chunk Search & Ranking with OpenAI`);

  // Step 1: Cleanup test document if it exists
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

  // Step 5: Open the chunk viewer
  logger.info(`  📖 Opening chunk viewer...`);
  await knowledge.openDocument(TEST_DOCUMENT);
  logger.info(`  ✓ Chunk viewer opened`);

  // Step 6: Test chunk search for multiple tokens
  logger.info(
    `\n  🔍 Testing chunk search for ${TEST_TOKENS.length} unique tokens...`,
  );

  let successCount = 0;
  let failureCount = 0;
  const failures: string[] = [];

  for (const token of TEST_TOKENS) {
    logger.info(`\n  🔎 Searching for token: ${token}`);

    // Search for the token and get top 2 chunks
    const top2Chunks = await knowledge.searchChunks(token);

    // Log the results
    logger.info(`     📊 Top 2 chunks retrieved:`);
    top2Chunks.forEach((chunk, index) => {
      const preview = chunk.substring(0, 100).replace(/\n/g, " ");
      const hasToken = chunk.includes(token);
      const indicator = hasToken ? "✓" : "✗";
      logger.info(`     ${indicator} ${index + 1}. ${preview}...`);
    });

    // Validation 1: Check if token appears in any of the top 2 chunks
    const tokenFoundInTop2 = top2Chunks.some((chunk) => chunk.includes(token));

    if (tokenFoundInTop2) {
      logger.info(`     ✅ Token found in top 2 chunks`);
      successCount++;
    } else {
      logger.info(`     ❌ Token NOT found in top 2 chunks`);
      failureCount++;
      failures.push(token);
    }
  }

  // Step 7: Report results
  logger.info(`\n  📈 Test Results Summary:`);
  logger.info(
    `     ✅ Successful searches: ${successCount}/${TEST_TOKENS.length}`,
  );
  logger.info(`     ❌ Failed searches: ${failureCount}/${TEST_TOKENS.length}`);

  if (failures.length > 0) {
    logger.info(`     Failed tokens: ${failures.join(", ")}`);
  }

  // Step 8: Assertions
  // We expect at least 80% success rate (8 out of 10 tokens)
  // This accounts for potential ranking variations across embedding models
  const successRate = successCount / TEST_TOKENS.length;
  const minSuccessRate = 0.8;

  logger.info(`\n  📊 Success rate: ${(successRate * 100).toFixed(1)}%`);
  logger.info(
    `  🎯 Required success rate: ${(minSuccessRate * 100).toFixed(1)}%`,
  );

  if (successRate >= minSuccessRate) {
    logger.info(
      `  ✅ SUCCESS: Chunk search ranking is working correctly for OpenAI\n`,
    );
  } else {
    throw new Error(
      `❌ FAILED: Chunk search ranking below acceptable threshold\n` +
        `   Success rate: ${(successRate * 100).toFixed(1)}% (required: ${(minSuccessRate * 100).toFixed(1)}%)\n` +
        `   Failed tokens: ${failures.join(", ")}\n` +
        `   This indicates the embedding model is not ranking relevant chunks correctly.`,
    );
  }

  // Playwright assertions for reporting
  expect(successRate).toBeGreaterThanOrEqual(minSuccessRate);
  expect(successCount).toBeGreaterThanOrEqual(
    Math.ceil(TEST_TOKENS.length * minSuccessRate),
  );
});
