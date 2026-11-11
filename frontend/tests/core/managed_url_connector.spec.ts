import { expect, test } from "../utils/fixtures";
import { navigateToKnowledge } from "../utils/navigation";

test("managed URL connector creates a one-page website connection", async ({
  page,
}) => {
  test.setTimeout(90_000);

  const name = `Playwright website ${Date.now()}`;
  const startingUrl = "https://example.com/";
  let sourceId: string | undefined;

  try {
    await navigateToKnowledge(page);

    await page.getByRole("button", { name: /add knowledge/i }).click();
    await page.getByRole("menuitem", { name: "URL" }).click();

    const dialog = page.getByRole("dialog", {
      name: "Add a Website connection",
    });
    await expect(dialog).toBeVisible();

    await dialog.getByLabel("Connection name").fill(name);
    await dialog.getByLabel("Starting URL").fill(startingUrl);
    await dialog.getByRole("button", { name: "This page only" }).click();
    await dialog
      .getByRole("button", { name: "Advanced crawl settings" })
      .click();
    await dialog.getByLabel("Change detection").click();
    await page.getByRole("option", { name: "Always re-ingest" }).click();

    await dialog.getByRole("button", { name: "Continue" }).click();
    await expect(
      dialog.getByRole("heading", { name: "How should re-syncs work?" }),
    ).toBeVisible();

    const createResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/connectors/url/sources") &&
        response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Ingest URL" }).click();

    const response = await createResponse;
    expect(response.ok()).toBe(true);
    expect(response.request().postDataJSON()).toMatchObject({
      name,
      starting_url: startingUrl,
      scope: "page",
      max_depth: 0,
      max_pages: 1,
      change_detection: "always_reingest",
    });
    const source = (await response.json()) as { id: string; name: string };
    sourceId = source.id;
    expect(source.name).toBe(name);
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Website crawl started")).toBeVisible();

    const sourcesResponse = await page.request.get(
      "/api/connectors/url/sources",
    );
    expect(sourcesResponse.ok()).toBe(true);
    const sources = (await sourcesResponse.json()) as {
      sources: { id: string; name: string; change_detection: string }[];
    };
    expect(sources.sources).toContainEqual(
      expect.objectContaining({
        id: sourceId,
        name,
        change_detection: "always_reingest",
      }),
    );
  } finally {
    if (sourceId) {
      const deleteResponse = await page.request.delete(
        `/api/connectors/url/sources/${sourceId}`,
      );
      expect(deleteResponse.ok()).toBe(true);
    }
  }
});
