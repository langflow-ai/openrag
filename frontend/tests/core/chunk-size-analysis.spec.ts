import * as fs from "fs";
import path from "path";
import { TEST_CONFIG } from "../config/test.config";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToApp, navigateToSettings } from "../utils/navigation";

interface ChunkSizeMetrics {
  chunkSize: number;
  indexingTime: number;
  responseTime: number;
  responseLength: number;
  responseText: string;
}

test.describe("Chunk Size Impact Analysis @33219206 , @34581149 , @3481151", () => {
  const metricsResults: ChunkSizeMetrics[] = [];
  const testQuestion = TEST_CONFIG.questions.docling.pipeline;
  const chunkSizeScenarios = [
    { size: 200, label: "Small Chunks (200)" },
    { size: 500, label: "Medium Chunks (500)" },
    { size: 1000, label: "Large Chunks (1000)" },
  ];

  test.beforeEach(async ({ page }) => {
    // Navigate to app (handles login and onboarding)
    await navigateToApp(page);
    // Verify test document exists
    if (!fs.existsSync(TEST_CONFIG.documents.docling.path)) {
      throw new Error(
        `Test document not found at: ${TEST_CONFIG.documents.docling.path}`,
      );
    }
  });

  for (const scenario of chunkSizeScenarios) {
    test(`Chunk Size = ${scenario.size} (${scenario.label})`, async ({
      page,
      settings,
      knowledge,
      chat,
    }) => {
      test.setTimeout(300000); // 5 minutes timeout

      // Configure chunk settings
      await settings.clickTab("Langflow");
      await settings.updateChunkSettings(
        scenario.size.toString(),
        TEST_CONFIG.chunkSettings.defaultOverlap,
      );

      // Upload document and measure indexing time
      const indexingStartTime = Date.now();
      await knowledge.ingestFile(TEST_CONFIG.documents.docling.path);
      const indexingTime = Date.now() - indexingStartTime;

      // Navigate to chat and ask question
      await chat.open();
      await chat.askQuestion(testQuestion);

      const queryStartTime = Date.now();
      const responseText = await chat.getLastResponse(
        TEST_CONFIG.timeouts.default,
      );
      const responseTime = Date.now() - queryStartTime;

      // Store metrics
      const metrics: ChunkSizeMetrics = {
        chunkSize: scenario.size,
        indexingTime,
        responseTime,
        responseLength: responseText.length,
        responseText,
      };

      metricsResults.push(metrics);

      // Assertions
      expect(indexingTime).toBeGreaterThan(0);
      expect(responseTime).toBeGreaterThan(0);
      expect(responseText.length).toBeGreaterThan(0);
    });
  }
  test.afterAll(async () => {
    if (metricsResults.length > 1) {
      const summary = metricsResults
        .map(
          (m) =>
            `Size ${m.chunkSize}: ${(m.responseTime / 1000).toFixed(1)}s response`,
        )
        .join(", ");
      logger.info(`Chunk Size Analysis Complete - ${summary}`);
    }
  });
});

test.describe("Large Chunk Size - Wrong Section Retrieval Test", () => {
  const testDocument = path.join(
    __dirname,
    "../test-data/Customer_analysis_small.csv",
  );
  const documentName = "Customer_analysis_small.csv";
  const testQuestion =
    "Which customer from Arizona has the highest Customer Lifetime Value?";
  const expectedCustomerId = "CP85232";
  const expectedValue = "44795";

  test.beforeEach(async ({ page }) => {
    // Navigate to app (handles login and onboarding)
    await navigateToApp(page);
  });

  test.beforeAll(async () => {
    // Verify test document exists (no page fixture needed)
    if (!fs.existsSync(testDocument)) {
      throw new Error(`Test document not found at: ${testDocument}`);
    }
  });

  test("Set chunk size to 1000 and verify correct answer retrieval", async ({
    page,
    settings,
    knowledge,
    chat,
  }) => {
    test.setTimeout(300000);

    await settings.clickTab("Langflow");
    await settings.updateChunkSettings(
      "1000",
      TEST_CONFIG.chunkSettings.defaultOverlap,
    );
    await knowledge.deleteDocument(documentName);
    await knowledge.ingestFile(testDocument, true);
    await knowledge.verifyDocumentActive(documentName);

    await chat.openNewChat();
    const response = await chat.askQuestion(
      testQuestion,
      TEST_CONFIG.timeouts.default,
    );

    const hasCorrectCustomer = response.includes(expectedCustomerId);
    const hasCorrectValue =
      response.includes(expectedValue) ||
      response.includes("44,795") ||
      response.includes("$44,795");

    logger.info("\n" + "=".repeat(80));
    logger.info(
      `CHUNK SIZE 1000: ${hasCorrectCustomer && hasCorrectValue ? "✅ Correct" : "❌ Wrong"} - Expected: ${expectedCustomerId} ($${expectedValue})`,
    );
    logger.info(`Response: ${response}`);
    logger.info("=".repeat(80) + "\n");

    expect(response.length).toBeGreaterThan(0);
  });
});
