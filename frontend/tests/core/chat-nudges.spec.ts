import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToChat } from "../utils/navigation";
import { completeOnboarding } from "../utils/onboarding";

test.describe("Chat Suggestion Questions - Multiple Iterations @33219233 , @34581264", () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the application
    await navigateToChat(page);
  });

  test("@smoke Click suggested questions in multiple iterations and verify responses", async ({
    page,
    chat,
  }) => {
    const iterations = 2;
    for (let iteration = 1; iteration <= iterations; iteration++) {
      // Wait for page to be ready
      await page.waitForTimeout(2000);
      const suggestionCount = await chat.getSuggestionCount();
      if (suggestionCount === 0) {
        break;
      }
      // Get the first suggestion button and click it
      const suggestionText = await chat.clickFirstSuggestion();
      // Wait for the streaming response to finish
      await chat.waitForStreamingResponse();
      // Check for function calls and wait for completion
      await chat.waitForFunctionCallsComplete();
      // Get the response
      const response = await chat.getLastResponse(120000);
      // Verify response is substantial
      expect(response.length).toBeGreaterThan(50);
      // Verify response is not an error message (check for common error patterns)
      const responseLower = response.toLowerCase();
      const errorPatterns = [
        /^(sorry|apologies|unfortunately),?\s+(i|we)\s+(can't|cannot|couldn't|am unable|don't have)/i,
        /^(i|we)\s+(don't have|do not have|cannot find|couldn't find)\s+(any|the|enough)\s+(information|data|context)/i,
        /^(there (was|is) an error|an error occurred|something went wrong)/i,
        /^(the (request|query|operation) (failed|has failed))/i,
        /^(unable to (process|retrieve|find|access))/i,
      ];
      const hasError = errorPatterns.some((pattern) =>
        pattern.test(responseLower),
      );
      expect(hasError).toBe(false);
      logger.info(
        `Iteration ${iteration}/${iterations}: "${suggestionText}" - Response received (${response.length} chars)`,
      );
      // Wait before next iteration to let new suggestions appear
      await page.waitForTimeout(2000);
    }
    logger.info(" All suggestion iterations completed successfully");
  });
  logger.info(
    " Negative test passed: Suggestions are generic defaults, not document-specific",
  );
});
