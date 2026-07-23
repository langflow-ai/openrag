import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToKnowledge } from "../utils/navigation";

test.describe("Fetch Latest Docs Functionality", () => {
  test("Verify Fetch Latest Docs works and refreshes the document list with and without Langflow @33219240", async ({
    page,
    knowledge,
    settings,
  }) => {
    test.setTimeout(360000); // 6 minutes timeout

    logger.info("Starting Fetch Latest Docs E2E test");
    const expectedDocName = "What is OpenRAG? | OpenRAG";

    // Navigate initially to load the app UI (sidebar with Settings link)
    await navigateToKnowledge(page);
    logger.info("Successfully loaded the app UI");

    // --- Phase 1: Test with Langflow Ingestion DISABLED (Traditional OpenRAG processing) ---
    logger.info("PHASE 1: Testing with Langflow Ingestion DISABLED");
    await settings.setDisableLangflowIngestion(true);

    await navigateToKnowledge(page);
    logger.info("Successfully navigated to Knowledge page");

    logger.info("Triggering fetchLatestDocs()...");
    await knowledge.fetchLatestDocs();
    logger.info("fetchLatestDocs() execution completed successfully");

    logger.info(`Verifying default document '${expectedDocName}' is active`);
    await knowledge.verifyDocumentActive(expectedDocName);

    // --- Phase 2: Test with Langflow Ingestion ENABLED (Langflow processing) ---
    logger.info("PHASE 2: Testing with Langflow Ingestion ENABLED");
    await settings.setDisableLangflowIngestion(false);

    await navigateToKnowledge(page);
    logger.info("Successfully navigated to Knowledge page");

    logger.info("Triggering fetchLatestDocs()...");
    await knowledge.fetchLatestDocs();
    logger.info("fetchLatestDocs() execution completed successfully");

    logger.info(`Verifying default document '${expectedDocName}' is active`);
    await knowledge.verifyDocumentActive(expectedDocName);

    logger.info(
      "Fetch Latest Docs E2E test passed successfully for both modes!",
    );
  });
});
