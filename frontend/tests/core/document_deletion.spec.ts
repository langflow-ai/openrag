import path from "path";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

test("Document deletion verification @33219237", async ({
  page,
  knowledge,
  chat,
  cleanupDocuments,
}) => {
  test.setTimeout(300000); // 5 minutes

  const testDocumentPath = path.join(
    __dirname,
    "../test-data/Project.code.for.QA.validation.is.ZX.docx",
  );
  const testDocumentName = "Project.code.for.QA.validation.is.ZX.docx";
  const verificationCode = "ZX-4819-RAG";
  const verificationQuestion = "what is project code for QA validation";

  await navigateToHome(page);

  // Cleanup and setup
  await knowledge.deleteDocument(testDocumentName);
  //await cleanupDocuments([testDocumentName]);
  // Ingest document
  await knowledge.ingestFile(testDocumentPath);
  await knowledge.verifyDocumentActive(testDocumentName);

  // Test with document present
  await chat.openNewChat();
  const response1 = await chat.askQuestion(verificationQuestion);
  expect(response1).toContain(verificationCode);

  // Delete document
  const deleteSuccess = await knowledge.deleteDocument(testDocumentName);
  expect(deleteSuccess).toBe(true);

  // Verify document removed
  await knowledge.verifyDocumentDeleted(testDocumentName);

  // Test after document deletion
  await chat.openNewChat();
  const response2 = await chat.askQuestion(verificationQuestion);
  expect(response2).not.toContain(verificationCode);

  logger.info("Document Deletion Test: PASSED");
});
