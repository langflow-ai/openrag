import path from "path";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

test("@smoke Knowledge filter functionality @33219234", async ({
  page,
  knowledge,
  chat,
  cleanupDocuments,
}) => {
  test.setTimeout(360000); // 6 minutes — Jenkins is slower; local took ~8 min total for all 3

  const testDocumentPath = path.join(
    __dirname,
    "../test-data/Leave.Policy.Test.Doc.pdf",
  );
  const testDocumentName = "Leave.Policy.Test.Doc.pdf";
  const filterName = "leave test";
  const testQuestion = "What is the leave policy?";

  await navigateToHome(page);

  // Cleanup and setup (skipFetch=true: no need for fresh grid data when deleting pre-test leftovers)
  await knowledge.deleteDocument(testDocumentName);
  await knowledge.deleteKnowledgeFilter(filterName);

  // Ingest document and create filter
  await knowledge.ingestFile(testDocumentPath);
  await knowledge.verifyDocumentActive(testDocumentName);
  await knowledge.createKnowledgeFilter(filterName, testDocumentName);

  // Test with filter and document
  await chat.openNewChat();
  await chat.applyKnowledgeFilter(filterName);
  const response1 = await chat.askQuestion(testQuestion);

  const hasSourceCitation = /source.*leave\.policy\.test\.doc\.pdf/i.test(
    response1,
  );
  const hasSpecificDetails =
    /earned leave|casual leave|sick leave|maternity leave|paternity leave|bereavement leave/i.test(
      response1,
    );
  const hasNumericDetails =
    /18 days|6 days|12 days|26 weeks|5 working days|3 days/i.test(response1);
  const hasDocumentContent =
    hasSourceCitation || (hasSpecificDetails && hasNumericDetails);

  expect(hasDocumentContent).toBe(true);

  // Delete document and test again
  const deleteSuccess = await knowledge.deleteDocument(testDocumentName);
  expect(deleteSuccess).toBe(true);

  await chat.openNewChat();
  await chat.applyKnowledgeFilter(filterName);
  const response2 = await chat.askQuestion(testQuestion);

  const lacksKnowledge =
    /no relevant.*sources|cannot find|no information|not available|unable to|don't have|no supporting/i.test(
      response2,
    );
  const hasDocumentSpecifics =
    /earned leave|casual leave|sick leave|18 days|6 days|12 days|26 weeks|source.*leave\.policy\.test\.doc/i.test(
      response2,
    );
  const isInadequate = lacksKnowledge || !hasDocumentSpecifics;

  expect(isInadequate).toBe(true);

  // Cleanup
  await knowledge.deleteKnowledgeFilter(filterName);

  logger.info("Knowledge Filter Test: PASSED");
});

test("Knowledge filter deletion verification", async ({
  page,
  knowledge,
  chat,
  cleanupDocuments,
}) => {
  test.setTimeout(300000); // 5 minutes — Jenkins is slower than local

  const testDocumentPath = path.join(
    __dirname,
    "../test-data/Leave.Policy.Test.Doc.pdf",
  );
  const testDocumentName = "Leave.Policy.Test.Doc.pdf";
  const filterName = "test-filter-deletion";

  await navigateToHome(page);

  // Cleanup and setup (skipFetch=true: avoid slow re-ingestion wait during pre-test cleanup)
  await knowledge.deleteDocument(testDocumentName);
  await knowledge.deleteKnowledgeFilter(filterName);

  // Ingest document and create filter
  await knowledge.ingestFile(testDocumentPath);
  await knowledge.verifyDocumentActive(testDocumentName);
  await knowledge.createKnowledgeFilter(filterName, testDocumentName);

  // Verify filter exists in chat
  await chat.openNewChat();
  const filterExistsBeforeDeletion = await chat.isFilterAvailable(filterName);
  expect(filterExistsBeforeDeletion).toBe(true);

  // Delete filter
  await knowledge.deleteKnowledgeFilter(filterName);

  // Verify filter no longer exists in chat
  await chat.openNewChat();
  const filterExistsAfterDeletion = await chat.isFilterAvailable(filterName);
  expect(filterExistsAfterDeletion).toBe(false);

  // Cleanup
  await knowledge.deleteDocument(testDocumentName);

  logger.info("Filter Deletion Test: PASSED");
});

test("Knowledge filter scope restriction - Negative test", async ({
  page,
  knowledge,
  chat,
  cleanupDocuments,
}) => {
  test.setTimeout(300000);

  const projectDocPath = path.join(
    __dirname,
    "../test-data/Project.code.for.QA.validation.is.ZX.docx",
  );
  const projectDocName = "Project.code.for.QA.validation.is.ZX.docx";
  const leavePolicyPath = path.join(
    __dirname,
    "../test-data/Leave.Policy.Test.Doc.pdf",
  );
  const leavePolicyName = "Leave.Policy.Test.Doc.pdf";
  const filterName = "project-code-only";
  const leaveQuestion = "What is the leave policy?";

  await navigateToHome(page);
  logger.info(`\n🧪 Testing Knowledge Filter Scope Restriction`);

  // Cleanup (skipFetch=true: no need for fresh grid data when deleting pre-test leftovers)
  await knowledge.deleteDocument(projectDocName);
  await knowledge.deleteDocument(leavePolicyName);
  await knowledge.deleteKnowledgeFilter(filterName);

  // Ingest both documents
  logger.info(`  📄 Ingesting documents...`);
  await knowledge.ingestFile(projectDocPath);
  await knowledge.verifyDocumentActive(projectDocName);
  await knowledge.ingestFile(leavePolicyPath);
  await knowledge.verifyDocumentActive(leavePolicyName);
  logger.info(`  ✓ Both documents ingested`);

  // Create filter with ONLY project code document
  await knowledge.createKnowledgeFilter(filterName, projectDocName);
  logger.info(`  ✓ Filter created with only: ${projectDocName}`);

  // Apply filter and ask about leave policy (which is NOT in the filter)
  await chat.openNewChat();
  await chat.applyKnowledgeFilter(filterName);
  const response = await chat.askQuestion(leaveQuestion);
  logger.info(`  ✓ Asked: "${leaveQuestion}"`);

  // Verify filter restricts retrieval (document not found in filtered scope)
  const indicatesNotFound =
    /no relevant.*sources|cannot find|didn't find|couldn't find|not available|unable to|don't have|no supporting|no.*matching/i.test(
      response,
    );

  expect(indicatesNotFound).toBe(true);
  logger.info(
    `  ✓ Filter restricted retrieval scope (leave policy not accessible)`,
  );

  // Cleanup
  await knowledge.deleteKnowledgeFilter(filterName);
  await knowledge.deleteDocument(projectDocName);
  await knowledge.deleteDocument(leavePolicyName);

  logger.info(`  ✅ Filter scope restriction verified\n`);
});
