import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToKnowledge } from "../utils/navigation";

test.describe("Fetch Latest Docs Functionality", () => {
  test("Verify Fetch Latest Docs works and refreshes the document list @33219240", async ({
    page,
    knowledge,
  }) => {
    test.setTimeout(180000); // 3 minutes timeout

    logger.info("Starting Fetch Latest Docs E2E test");

    // 1. Navigate to the Knowledge page
    await navigateToKnowledge(page);
    logger.info("Successfully navigated to Knowledge page");

    // 2. Click the "Fetch latest docs" button and verify success toast is shown
    logger.info("Triggering fetchLatestDocs()...");
    await knowledge.fetchLatestDocs();
    logger.info("fetchLatestDocs() execution completed successfully");

    // 3. Verify that the OpenRAG docs URL document appears and becomes active
    const expectedDocName =
      process.env.DEFAULT_DOCS_URL || "https://docs.openr.ag/";
    logger.info(`Verifying default document '${expectedDocName}' is active`);
    await knowledge.verifyDocumentActive(expectedDocName);

    logger.info("Fetch Latest Docs E2E test passed successfully!");
  });
});
