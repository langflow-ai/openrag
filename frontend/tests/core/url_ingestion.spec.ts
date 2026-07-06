import { OPENAI_CONFIG } from "../config/provider";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

test("@smoke URL connector ingestion reliability - OpenAI @33219228", async ({
  page,
  settings,
  knowledge,
  chat,
  cleanupDocuments,
}) => {
  test.setTimeout(180000);

  // Navigate to the application
  await navigateToHome(page);

  logger.info(`\n🧪 Testing URL Ingestion with OpenAI`);

  // Step 1: Cleanup test document if it exists
  logger.info(`  🧹 Cleaning up existing test document...`);
  const docName = OPENAI_CONFIG.testCase.docName;
  try {
    await knowledge.deleteDocument(docName);
    logger.info(`  ✓ Test document cleaned up`);
  } catch (_error) {
    logger.info(`  ℹ️  No existing test document to clean up`);
  }

  // Register document for cleanup after test
  await cleanupDocuments([docName]);

  // Step 2: Set models for OpenAI
  logger.info(`  ⚙️  Setting models for OpenAI...`);
  await settings.clickTab("Langflow");
  await settings.selectModel("Language model", OPENAI_CONFIG.language);
  await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);
  logger.info(`  ✓ Language model set to: ${OPENAI_CONFIG.language}`);
  logger.info(`  ✓ Embedding model set to: ${OPENAI_CONFIG.embedding}`);

  // Step 3: Ingest URL via chat
  logger.info(`  🌐 Ingesting URL: ${OPENAI_CONFIG.testCase.url}`);
  await chat.open();
  const { toolCall, toolData } = await chat.ingestUrl(
    OPENAI_CONFIG.testCase.url,
  );
  logger.info(`  ✓ URL ingestion initiated`);

  // Step 4: Verify tool call arguments
  logger.info(`  🔍 Verifying tool call arguments...`);
  expect(toolData).toBeDefined();
  expect(toolData.tool_name).toBe("opensearch_url_ingestion_flow");
  expect(toolData.inputs.input_value).toBe(OPENAI_CONFIG.testCase.url);
  logger.info(
    `  ✓ Tool called with correct URL: ${toolData.inputs.input_value}`,
  );

  // Step 5: Verify ingestion succeeded (tool did not fail)
  logger.info(`  ⏳ Verifying ingestion success...`);
  const failedTool = await chat.isToolFailed(toolCall);
  expect(failedTool).toBe(false);
  logger.info(`  ✓ Ingestion completed without errors`);

  // Step 6: Verify document is active in knowledge base
  logger.info(`  📄 Verifying document in knowledge base...`);
  await knowledge.verifyDocumentActive(docName);
  logger.info(`  ✓ Document "${docName}" is active in knowledge base`);

  // Success!
  logger.info(`  ✅ SUCCESS: URL ingestion verified for OpenAI\n`);

  // Assertions for Playwright reporting
  expect(failedTool).toBe(false);
});

test("URL connector ingestion - Invalid URL handling @34581217", async ({
  page,
  settings,
  chat,
}) => {
  test.setTimeout(180000);

  await navigateToHome(page);
  logger.info(`\n🧪 Testing Invalid URL Ingestion`);

  // Set models
  await settings.clickTab("Langflow");
  await settings.selectModel("Language model", OPENAI_CONFIG.language);
  await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);

  // Attempt to ingest invalid URL
  const invalidUrl = "http://www.invalid-url.com";
  logger.info(`  🌐 Ingesting invalid URL: ${invalidUrl}`);
  await chat.open();
  const { toolData, fullResponse } = await chat.ingestUrl(invalidUrl);

  // Verify tool call input (ensures failure is not due to incorrect input)
  expect(toolData).toBeDefined();
  expect(toolData.inputs.input_value).toBe(invalidUrl);
  logger.info(`  ✓ Tool called with correct URL`);

  // Verify chat response contains error message and helpful guidance
  // Check for failure indication
  expect(fullResponse).toMatch(/failed|error/i);

  // Check for specific error message indicating ingestion failure (LLM wording varies)
  expect(fullResponse).toMatch(
    /no documents were (successfully )?loaded|ingestion failed|dns resolution failed|failed to (load|fetch|ingest)|error.*ingestion|ingestion.*error/i,
  );

  // Check for helpful next steps or guidance (flexible patterns)
  const hasGuidance =
    /possible (next )?steps|what (would you like|can I do)|next steps|confirm|provide|try/i.test(
      fullResponse,
    );
  expect(hasGuidance).toBe(true);

  logger.info(`  ✓ Error message and guidance provided`);

  logger.info(`  ✅ Invalid URL handling verified\n`);
});

test("URL connector ingestion - Authentication-blocked URL handling @34581218", async ({
  page,
  settings,
  chat,
}) => {
  test.setTimeout(180000);

  await navigateToHome(page);
  logger.info(`\n🧪 Testing Authentication-Blocked URL Ingestion`);

  // Set models
  await settings.clickTab("Langflow");
  await settings.selectModel("Language model", OPENAI_CONFIG.language);
  await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);

  // Attempt to ingest authentication-blocked URL
  const authBlockedUrl = "https://github.com/settings/profile";
  logger.info(`  🌐 Ingesting authentication-blocked URL: ${authBlockedUrl}`);
  await chat.open();
  const { toolData, fullResponse } = await chat.ingestUrl(authBlockedUrl);

  // Verify tool call input (ensures failure is not due to incorrect input)
  expect(toolData).toBeDefined();
  expect(toolData.inputs.input_value).toBe(authBlockedUrl);
  logger.info(`  ✓ Tool called with correct URL`);

  // Verify chat response contains authentication/authorization message
  // Check for authentication-related keywords
  const hasAuthMessage =
    /authentication|authorization|sign.?in|log.?in|requires being signed in|not accessible without/i.test(
      fullResponse,
    );
  expect(hasAuthMessage).toBe(true);
  logger.info(`  ✓ Response indicates authentication is required`);

  // Verify response mentions the URL or GitHub
  const mentionsSource = /github|settings\/profile/i.test(fullResponse);
  expect(mentionsSource).toBe(true);
  logger.info(`  ✓ Response mentions the blocked URL source`);

  logger.info(`  ✅ Authentication-blocked URL handling verified\n`);
});

test("URL ingestion persists after conversation deletion @34581222", async ({
  page,
  settings,
  chat,
  cleanupDocuments,
}) => {
  test.setTimeout(180000);

  await navigateToHome(page);
  logger.info(
    `\n🧪 Testing URL Ingestion Persistence After Conversation Deletion`,
  );

  // Step 1: Cleanup test document if it exists
  logger.info(`  🧹 Cleaning up existing test document...`);
  const testUrl = "https://playwright.dev/docs/locators";
  const docName = "Locators | Playwright";

  // Register document for cleanup after test
  await cleanupDocuments([docName]);

  // Step 2: Set models for OpenAI
  logger.info(`  ⚙️  Setting models for OpenAI...`);
  await settings.clickTab("Langflow");
  await settings.selectModel("Language model", OPENAI_CONFIG.language);
  await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);
  logger.info(`  ✓ Language model set to: ${OPENAI_CONFIG.language}`);
  logger.info(`  ✓ Embedding model set to: ${OPENAI_CONFIG.embedding}`);

  // Step 3: Ingest URL via chat
  logger.info(`  🌐 Ingesting URL: ${testUrl}`);
  await chat.open();
  const { toolCall, toolData } = await chat.ingestUrl(testUrl);
  logger.info(`  ✓ URL ingestion initiated`);

  // Step 4: Verify tool call arguments
  logger.info(`  🔍 Verifying tool call arguments...`);
  expect(toolData).toBeDefined();
  expect(toolData.tool_name).toBe("opensearch_url_ingestion_flow");
  expect(toolData.inputs.input_value).toBe(testUrl);
  logger.info(
    `  ✓ Tool called with correct URL: ${toolData.inputs.input_value}`,
  );

  // Step 5: Verify ingestion succeeded (tool did not fail)
  logger.info(`  ⏳ Verifying ingestion success...`);
  const failedTool = await chat.isToolFailed(toolCall);
  expect(failedTool).toBe(false);
  logger.info(`  ✓ Ingestion completed without errors`);

  // Step 6: Delete the conversation
  logger.info(`  🗑️  Deleting the conversation...`);
  const chatTitle = `Please ingest this URL: ${testUrl}`;
  await chat.deleteChatByTitle(chatTitle);
  logger.info(`  ✓ Conversation deleted successfully`);

  // Step 7: Open a new chat and ask a question related to the ingested URL
  logger.info(`  💬 Opening new chat and asking related question...`);
  await chat.openNewChat();
  const question = "What are the different types of locators in Playwright?";
  const response = await chat.askQuestion(question);
  logger.info(`  ✓ Received response to question`);

  // Step 8: Verify the response contains relevant information from the ingested URL
  logger.info(
    `  🔍 Verifying response contains information from ingested URL...`,
  );
  // Check if response has source citation from the ingested document first (short-circuit)
  // If it has "Source: Locators | Playwright", it's definitely using the ingested doc
  // Otherwise, check if it mentions locator types like getByRole, getByText, etc.
  const hasSourceFromIngestedDoc = /Source:.*Locators.*Playwright/i.test(
    response,
  );
  const hasRelevantInfo =
    hasSourceFromIngestedDoc ||
    /getByRole|getByText|getByLabel|getByPlaceholder|getByTestId|locator/i.test(
      response,
    );
  expect(hasRelevantInfo).toBe(true);
  logger.info(
    `  ✓ Response contains ${hasSourceFromIngestedDoc ? "source citation from" : "relevant information about"} ingested URL`,
  );

  // Step 9: Verify response does NOT contain "no relevant sources" message
  logger.info(
    `  🔍 Verifying response is from ingested URL (not external sources)...`,
  );
  const hasNoSourcesMessage =
    /no relevant supporting sources|no supporting sources|couldn't find relevant|no relevant information/i.test(
      response,
    );
  expect(hasNoSourcesMessage).toBe(false);
  logger.info(
    `  ✓ Response is based on ingested URL data (no "no sources" message)`,
  );

  // Success!
  logger.info(
    `  ✅ SUCCESS: URL ingestion persists after conversation deletion\n`,
  );

  // Assertions for Playwright reporting
  expect(failedTool).toBe(false);
  expect(hasRelevantInfo).toBe(true);
  expect(hasNoSourcesMessage).toBe(false);
});
