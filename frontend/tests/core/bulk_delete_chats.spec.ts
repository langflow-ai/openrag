import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

test("Bulk delete: deleting selected chats removes them and keeps the rest", async ({
  page,
  chat,
}) => {
  test.setTimeout(120000);
  await navigateToHome(page);

  await chat.openNewChat();
  await chat.askQuestion("bulk probe alpha");
  await chat.openNewChat();
  await chat.askQuestion("bulk probe beta");
  await chat.openNewChat();
  await chat.askQuestion("bulk probe gamma");

  await chat.enterSelectionMode();
  await chat.selectConversationByTitle("bulk probe alpha");
  await chat.selectConversationByTitle("bulk probe beta");
  await chat.clickBulkDelete();

  await expect(
    page.getByTestId("conversation-button-bulk probe gamma"),
  ).toBeVisible({ timeout: 15000 });
  await expect(
    page.getByTestId("conversation-button-bulk probe alpha"),
  ).not.toBeVisible();
  await expect(
    page.getByTestId("conversation-button-bulk probe beta"),
  ).not.toBeVisible();

  logger.info("Bulk delete partial: PASSED");
});

test("Bulk delete: deleting all chats opens a fresh chat", async ({
  page,
  chat,
}) => {
  test.setTimeout(120000);
  await navigateToHome(page);

  await chat.openNewChat();
  await chat.askQuestion("bulk all probe one");
  await chat.openNewChat();
  await chat.askQuestion("bulk all probe two");

  await chat.enterSelectionMode();
  await chat.selectAllConversations();
  await chat.clickBulkDelete();

  await expect
    .poll(() => chat.getConversationCount(), { timeout: 30000 })
    .toBe(0);

  await expect(
    page.getByRole("textbox", { name: /ask a question/i }),
  ).toBeVisible();

  logger.info("Bulk delete all: PASSED");
});
