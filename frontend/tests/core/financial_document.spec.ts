import * as path from "path";
import { OPENAI_CONFIG } from "../config/provider";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

/**
 * Financial Document Ingestion Test Suite
 * Tests table structure extraction from financial documents (Walmart 10-Q)
 *
 * Configuration: Table Structure ON
 * Test 1: Basic table data retrieval (Total Net Sales for April 30, 2023: 151,004 million)
 * Test 2: Out-of-scope query (Tesla revenue - should not hallucinate)
 */

test.describe("Financial Document - OpenAI @33219232", () => {
  test("Table Structure ON - document Q&A", async ({
    page,
    settings,
    knowledge,
    chat,
  }) => {
    test.setTimeout(600000); // 10 minutes

    const testDocument = "WALMART_2024Q1_10Q.pdf";

    // Navigate to the application
    await navigateToHome(page);
    logger.info(`\n🧪 Testing Financial Document with OpenAI`);

    // Configure models
    await settings.open();
    await settings.clickTab("Langflow");
    await settings.selectModel("Language model", OPENAI_CONFIG.language);
    await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);
    logger.info(`  ✓ Language model set to: ${OPENAI_CONFIG.language}`);
    logger.info(`  ✓ Embedding model set to: ${OPENAI_CONFIG.embedding}`);

    await page.waitForLoadState("domcontentloaded");

    // Remove existing copy and re-ingest with table structure ON
    await knowledge.open();
    await knowledge.deleteDocument(testDocument);

    await settings.open();
    await settings.clickTab("Langflow");
    await settings.setTableStructure(true);

    await knowledge.open();
    const fileName = await knowledge.ingestFile(
      path.join(__dirname, "../test-data", testDocument),
    );
    await knowledge.verifyDocumentActive(fileName);

    // ── Test 1: Table data retrieval ──────────────────────────────────────────
    await chat.open();
    await chat.openNewChat();
    const q1 = "What is the total net sales for April 30, 2023?";
    const r1 = await chat.askQuestion(q1, 60000);
    logger.info(`  Test 1 response: ${r1.substring(0, 300)}`);

    // Accept any reasonable representation of 151,004 million
    const hasNetSales =
      r1.includes("151,004") ||
      r1.includes("151004") ||
      r1.includes("151.0") ||
      r1.includes("$151") ||
      /\b151[,.]?\d*\s*(billion|million|B|M)?\b/i.test(r1);

    expect(
      hasNetSales,
      `Expected response to contain ~151,004 million. Got: "${r1.substring(0, 300)}"`,
    ).toBe(true);

    // ── Test 2: Out-of-scope query (no hallucination) ─────────────────────────
    await chat.openNewChat();
    const q2 = "What is Tesla's revenue in this document?";
    const r2 = await chat.askQuestion(q2, 60000);
    logger.info(`  Test 2 response: ${r2.substring(0, 300)}`);

    const r2Lower = r2.toLowerCase();
    const hasHallucination =
      /\$?\d+[\d,]*\s*(million|billion|m|b)/i.test(r2) &&
      !r2Lower.includes("walmart");
    const indicatesNoInfo =
      r2Lower.includes("not") ||
      r2Lower.includes("no ") ||
      r2Lower.includes("don't") ||
      r2Lower.includes("doesn't") ||
      r2Lower.includes("cannot") ||
      r2Lower.includes("unable") ||
      r2Lower.includes("access") ||
      r2Lower.includes("document");

    expect(
      hasHallucination,
      `Model hallucinated Tesla revenue. Got: "${r2.substring(0, 300)}"`,
    ).toBe(false);
    expect(
      indicatesNoInfo,
      `Expected model to say Tesla info is not in the document. Got: "${r2.substring(0, 300)}"`,
    ).toBe(true);
  });
});
