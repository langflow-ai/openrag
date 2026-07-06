import * as fs from "fs";
import path from "path";
import { TEST_CONFIG } from "../config/test.config";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToApp } from "../utils/navigation";

interface ChunkOverlapMetrics {
  overlap: number;
  indexingTime: number;
  responseTime: number;
  responseLength: number;
  responseText: string;
}

test.describe("Chunk Overlap Impact Analysis @33219205 , @34581144 , @34581148", () => {
  const metricsResults: ChunkOverlapMetrics[] = [];
  const testQuestion = TEST_CONFIG.questions.docling.models;
  const overlapScenarios = [
    { overlap: 50, label: "Low Overlap (10%)" },
    { overlap: 100, label: "Medium Overlap (20%)" },
    { overlap: 150, label: "High Overlap (30%)" },
    { overlap: 200, label: "Very High Overlap (40%)" },
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

  for (const scenario of overlapScenarios) {
    test(`Chunk Overlap = ${scenario.overlap} (${scenario.label})`, async ({
      page,
      settings,
      knowledge,
      chat,
    }) => {
      test.setTimeout(300000); // 5 minutes timeout

      // Configure chunk settings (fixed size, variable overlap)
      await settings.clickTab("Langflow");
      await settings.updateChunkSettings(
        TEST_CONFIG.chunkSettings.defaultSize,
        scenario.overlap.toString(),
      );

      // Upload document and measure indexing time
      const indexingStartTime = Date.now();
      await knowledge.ingestFile(TEST_CONFIG.documents.docling.path);
      const indexingTime = Date.now() - indexingStartTime;

      // Navigate to chat and ask question
      await chat.open();

      const queryStartTime = Date.now();
      const responseText = await chat.askQuestion(
        testQuestion,
        TEST_CONFIG.timeouts.default,
      );
      const responseTime = Date.now() - queryStartTime;

      // Store metrics
      const metrics: ChunkOverlapMetrics = {
        overlap: scenario.overlap,
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
      const baseline = metricsResults[0];
      const final = metricsResults[metricsResults.length - 1];
      const timeChange = (
        (final.responseTime - baseline.responseTime) /
        1000
      ).toFixed(2);
      logger.info(
        `Chunk Overlap Analysis Complete - Response time change: ${timeChange}s (overlap ${baseline.overlap} → ${final.overlap})`,
      );
    }
  });
});

test.describe("Chunk Overlap Edge Case - Very Low Overlap with CSV Data", () => {
  const testDocument = path.join(
    __dirname,
    "../test-data/Customer_analysis_small.csv",
  );
  const documentName = "Customer_analysis_small.csv";
  const testQuestion =
    "Which customer has a higher Income: BU79786 or QZ44356?";

  test.beforeAll(async () => {
    if (!fs.existsSync(testDocument)) {
      throw new Error(`Test document not found at: ${testDocument}`);
    }
  });

  test.beforeEach(async ({ page }) => {
    // Navigate to app (handles login and onboarding)
    await navigateToApp(page);
  });

  test("Compare overlap=1 vs overlap=50 for the same question", async ({
    page,
    settings,
    knowledge,
    chat,
  }) => {
    test.setTimeout(600000);

    const results: Array<{
      overlap: string;
      response: string;
      quality: string;
    }> = [];

    // Test with both overlap values
    for (const overlap of ["1", "50"]) {
      await settings.clickTab("Langflow");
      await settings.updateChunkSettings(
        TEST_CONFIG.chunkSettings.defaultSize,
        overlap,
      );

      // Upload document (will overwrite if exists)
      await knowledge.ingestFile(testDocument, true);
      await knowledge.verifyDocumentActive(documentName);

      await chat.openNewChat();
      const response = await chat.askQuestion(
        testQuestion,
        TEST_CONFIG.timeouts.default,
      );

      // Analyze response
      const responseLower = response.toLowerCase();
      const mentionsBU79786 = responseLower.includes("bu79786");
      const mentionsQZ44356 = responseLower.includes("qz44356");
      const mentions56274 =
        response.includes("56274") || response.includes("56,274");
      const mentions2322 =
        response.includes("2322") || response.includes("2,322");

      let quality = "COMPLETE";
      if (!mentionsBU79786 || !mentionsQZ44356) {
        quality = "PARTIAL";
      } else if (!mentions56274 || !mentions2322) {
        quality = "INCOMPLETE";
      }

      results.push({ overlap, response, quality });
    }

    // Final comparison log
    if (results.length === 2) {
      const [result1, result50] = results;
      logger.info("\n" + "=".repeat(80));
      logger.info(
        `OVERLAP COMPARISON: ${result1.quality} (overlap=1) → ${result50.quality} (overlap=50)`,
      );
      logger.info("=".repeat(80));
      logger.info(`Overlap=1: ${result1.response}`);
      logger.info(`Overlap=50: ${result50.response}`);
      logger.info("=".repeat(80) + "\n");
    }

    // Assertions
    expect(results.length).toBeGreaterThan(0);
    results.forEach((result) => {
      expect(result.response.length).toBeGreaterThan(0);
    });
  });
});
