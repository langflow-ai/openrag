import { expect, Locator, Page } from "@playwright/test";
import logger from "./logger";
import { completeOnboarding } from "./onboarding";

/**
 * Get the base URL from environment or config
 */
export function getBaseUrl(): string {
  return process.env.BASE_URL || "http://localhost:3000";
}

/**
 * Build a full URL by properly joining base URL and path
 */
function buildUrl(path: string): string {
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}

/**
 * Core navigation handler with login support
 */
export async function navigateToApp(
  page: Page,
  path: string = "/",
): Promise<void> {
  const fullUrl = buildUrl(path);
  await page.goto(fullUrl);
  await completeOnboarding(page);
  // After onboarding, the app redirects to /chat, redirect to another path if needed
  if (!page.url().includes(path)) {
    logger.info(`Navigating to intended path: ${path}`);
    await page.goto(fullUrl);
    await page.waitForLoadState("networkidle");
  }
}

/**
 * Navigate to Chat page and verify textbox
 */
export async function navigateToChat(page: Page): Promise<void> {
  await navigateToApp(page, "/chat");
  await expect(
    page.getByRole("textbox", { name: "Ask a question..." }),
  ).toBeVisible({ timeout: 60000 });
}

/**
 * Navigate to Knowledge page and verify heading
 */
export async function navigateToKnowledge(page: Page): Promise<void> {
  await navigateToApp(page, "/knowledge");
  await expect(page.getByText("Project Knowledge")).toBeVisible({
    timeout: 60000,
  });
}

/**
 * Navigate to Settings page and verify heading
 */
export async function navigateToSettings(page: Page): Promise<void> {
  await navigateToApp(page, "/settings");
  // Check for either Providers text or Settings heading with ibm-section-title class
  const modelProvidersVisible = page.getByText("Providers").first();
  const settingsHeadingVisible = page.locator(
    'h2.ibm-section-title:has-text("Settings")',
  );

  // Wait for at least one of them to be visible
  await Promise.race([
    expect(modelProvidersVisible).toBeVisible({ timeout: 60000 }),
    expect(settingsHeadingVisible).toBeVisible({ timeout: 60000 }),
  ]);
}

/**
 * Navigate to Home (optional: treat as chat)
 */
export async function navigateToHome(page: Page): Promise<void> {
  await navigateToChat(page);
}
