import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

test("Model switching transitions (Language + Embedding) - OpenAI @33219223, @33219222", async ({
  page,
  settings,
}) => {
  test.setTimeout(300000);

  // Navigate to the application
  await navigateToHome(page);

  logger.info("\n🧪 Testing Model Switching with OpenAI");
  await settings.clickTab("Langflow");

  // OpenAI model sequences for testing transitions
  const languageSequence = ["gpt-4o", "gpt-4o-mini", "gpt-4o"]; // Circular: A→B→A
  const embeddingSequence = [
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-3-small",
  ]; // Circular: A→B→A

  logger.info(`\n📋 Transition sequence (circular):`);
  logger.info(`   Language models: ${languageSequence.join(" → ")}`);
  logger.info(`   Embedding models: ${embeddingSequence.join(" → ")}`);

  // Test Language model transitions
  logger.info(`\n🔄 Testing Language model transitions...`);
  const languageFailures: string[] = [];

  for (let i = 0; i < languageSequence.length - 1; i++) {
    const from = languageSequence[i];
    const to = languageSequence[i + 1];

    logger.info(`  ${from} → ${to}`);

    try {
      await settings.selectModel("Language model", to);
      logger.info(`  ✓ Success`);
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      logger.error(`  ❌ FAILED: ${errorMessage}`);
      languageFailures.push(`${from} → ${to}`);
    }
  }

  // Test Embedding model transitions
  logger.info(`\n🔄 Testing Embedding model transitions...`);
  const embeddingFailures: string[] = [];

  for (let i = 0; i < embeddingSequence.length - 1; i++) {
    const from = embeddingSequence[i];
    const to = embeddingSequence[i + 1];

    logger.info(`  ${from} → ${to}`);

    try {
      await settings.selectModel("Embedding model", to);
      logger.info(`  ✓ Success`);
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      logger.error(`  ❌ FAILED: ${errorMessage}`);
      embeddingFailures.push(`${from} → ${to}`);
    }
  }

  // Summary
  logger.info(`\n📊 Test Summary:`);
  logger.info(
    `   Tested transitions: ${languageSequence.length - 1} language, ${embeddingSequence.length - 1} embedding`,
  );
  logger.info(`   Language failures: ${languageFailures.length}`);
  logger.info(`   Embedding failures: ${embeddingFailures.length}`);

  if (languageFailures.length > 0) {
    logger.info(`\n❌ Language model transition failures:`);
    languageFailures.forEach((f) => logger.info(`   - ${f}`));
  }

  if (embeddingFailures.length > 0) {
    logger.info(`\n❌ Embedding model transition failures:`);
    embeddingFailures.forEach((f) => logger.info(`   - ${f}`));
  }

  // Assert no failures
  expect(languageFailures.length).toBe(0);
  expect(embeddingFailures.length).toBe(0);
});
