import { Page } from "@playwright/test";
import { Settings } from "../pages/Settings";

/**
 * Utility to detect which model providers are configured
 */
export class ProviderDetector {
  constructor(
    private page: Page,
    private settings: Settings,
  ) {}

  /**
   * Check if a provider is configured by checking the button text
   * Configured providers show "Edit Setup", unconfigured show "Configure"
   * @param providerName - Name of the provider (e.g., "OpenAI", "Ollama", "IBM watsonx.ai", "Anthropic")
   * @returns true if provider is configured (has "Edit Setup" button), false otherwise
   */
  async isProviderConfigured(providerName: string): Promise<boolean> {
    await this.settings.open();

    // Wait for Providers section to be visible
    await this.page
      .getByText("Providers")
      .waitFor({ state: "visible", timeout: 10000 });

    // Find the heading that contains the provider name
    const providerHeading = this.page
      .locator("h3")
      .filter({ hasText: providerName });

    try {
      await providerHeading.waitFor({ state: "visible", timeout: 10000 });
    } catch {
      return false; // Provider heading not found
    }

    // Navigate up to the parent card container (the card is typically 3-4 levels up from h3)
    // We'll look for the nearest ancestor that contains both the heading and buttons
    const providerCard = providerHeading.locator(
      'xpath=ancestor::div[.//button[contains(text(), "Edit Setup") or contains(text(), "Configure")]][1]',
    );

    try {
      await providerCard.waitFor({ state: "visible", timeout: 5000 });
    } catch {
      return false; // Provider card not found
    }

    // Check if "Edit Setup" button exists (configured) vs "Configure" (not configured)
    const editSetupButton = providerCard.getByRole("button", {
      name: "Edit Setup",
    });
    const isConfigured = await editSetupButton.isVisible().catch(() => false);

    return isConfigured;
  }

  /**
   * Get all configured providers
   * @returns Array of configured provider names
   */
  async getConfiguredProviders(): Promise<string[]> {
    const providers = ["OpenAI", "Ollama", "IBM watsonx.ai", "Anthropic"];
    const configured: string[] = [];

    for (const provider of providers) {
      if (await this.isProviderConfigured(provider)) {
        configured.push(provider);
      }
    }

    return configured;
  }
}
