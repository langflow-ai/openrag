import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

test("Bulk delete: deleting selected chats removes them and keeps the rest", async ({
  page,
  chat,
}) => {
  test.setTimeout(120000);
  await navigateToHome(page);

  // Conversations persist in a shared DB with no per-test cleanup, and the
  // sidebar testid is keyed on the conversation title. A unique per-run suffix
  // keeps this run's chats from colliding with leftovers of prior runs
  // (duplicate testids → strict-mode violations / ambiguous visibility checks).
  const id = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const alpha = `bulk probe alpha ${id}`;
  const beta = `bulk probe beta ${id}`;
  const gamma = `bulk probe gamma ${id}`;

  await chat.openNewChat();
  await chat.askQuestion(alpha);
  await chat.openNewChat();
  await chat.askQuestion(beta);
  await chat.openNewChat();
  await chat.askQuestion(gamma);

  // All rows present before selecting, so their ids are in the list.
  await expect(page.getByTestId(`conversation-button-${gamma}`)).toBeVisible({
    timeout: 30000,
  });

  await chat.enterSelectionMode();
  await chat.selectConversationByTitle(alpha);
  await chat.selectConversationByTitle(beta);
  await chat.clickBulkDelete();

  // Selected chats disappear from the sidebar; the unselected one remains.
  await expect(page.getByTestId(`conversation-button-${alpha}`)).toBeHidden({
    timeout: 30000,
  });
  await expect(page.getByTestId(`conversation-button-${beta}`)).toBeHidden({
    timeout: 30000,
  });
  await expect(page.getByTestId(`conversation-button-${gamma}`)).toBeVisible();

  logger.info("Bulk delete partial: PASSED");
});
