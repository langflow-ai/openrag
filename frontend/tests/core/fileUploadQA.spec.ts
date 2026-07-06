import path from "path";
import { expect, test } from "../utils/fixtures";
import { navigateToChat } from "../utils/navigation";

const testDocumentPath = path.join(
  __dirname,
  "../test-data/Customer_analysis_small.csv",
);
const verificationQuestion =
  "what is the monthly premium for the customer BU79786?";

/**
 * Test: Document Upload and Q&A Verification
 * Verifies that uploaded documents are correctly ingested and system can retrieve accurate information.
 */
test.describe("Upload a specific file in the chat interface and ask a contextually relevant question about its content @33219209", () => {
  test.skip("@smoke Upload a file in the chat and ask a question", async ({
    page,
    chat,
  }) => {
    await navigateToChat(page);
    const fileName = await chat.ingestFileInChat(testDocumentPath);
    // Increase timeout to 120 seconds for large PDF processing
    const response = await chat.askQuestion(verificationQuestion, 120000);
    expect(
      ["BU79786", "69"].every((keyword) => response.includes(keyword)),
    ).toBe(true);
    await chat.verifyFileInChat(fileName);
  });
});
