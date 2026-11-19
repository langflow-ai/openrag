import { expect, test } from "@playwright/test";
import { completeOnboarding } from "../utils/onboarding";

/**
 * Full-stack flow: stream an answer -> rate it -> reload -> the vote is
 * restored from the persisted message. Also covers the Activity guard. Needs the Docker stack; it is skipped by Vitest.
 *
 * The Activity assertions need OPENRAG_RBAC_ENFORCE=true with an admin user;
 * with RBAC off they assert the documented denial instead.
 */
test("feedback persists across reload", async ({ page }) => {
  await completeOnboarding(page, { reset: true });

  await page.getByTestId("chat-input").fill("What is OpenRAG?");
  await page.getByTestId("send-button").click();

  const like = page.getByRole("button", { name: "Like", exact: true });
  // Controls appear only after the answer row has been committed.
  await expect(like).toBeVisible({ timeout: 90000 });

  const saved = page.waitForResponse((r) =>
    /\/api\/chat\/[^/]+\/messages\/[^/]+\/feedback$/.test(r.url()),
  );
  await like.click();
  expect((await saved).status()).toBe(200);
  await expect(like).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await page
    .getByTestId("conversation-button-What is OpenRAG?")
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "Like", exact: true }),
  ).toHaveAttribute("aria-pressed", "true", { timeout: 30000 });
});

test("activity tab is guarded", async ({ page }) => {
  await completeOnboarding(page, { reset: false });
  const me = await (await page.request.get("/api/users/me")).json();

  await page.goto("/settings/activity");
  if (!me.activity_access) {
    // Server-side guard redirects; the tab is not rendered.
    await expect(page).toHaveURL(/\/settings\/connectors/);
    await expect(page.getByRole("link", { name: "Activity" })).toHaveCount(0);
    const denied = await page.request.get("/api/activity/feedback/summary");
    expect(denied.status()).toBe(403);
    return;
  }

  await expect(page.getByText(/feedback satisfaction/i)).toBeVisible();
});
