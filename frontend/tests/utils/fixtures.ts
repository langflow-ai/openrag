import { test as base, Page } from "@playwright/test";
import { Chat } from "../pages/Chat";
import { Knowledge } from "../pages/Knowledge";
import { Settings } from "../pages/Settings";
import logger from "./logger";

type TestFixtures = {
  settings: Settings;
  knowledge: Knowledge;
  chat: Chat;
  cleanupDocuments: (documentNames: string[]) => Promise<void>;
  route: string;
  skipBeforeEach: boolean;
};

/**
 * Extended test with custom fixtures for OpenRAG UI testing
 * Provides page objects and cleanup utilities
 *
 * Route Configuration:
 * - For default route (http://localhost:3000): Skip test.use() and begin directly
 * - For /chat route: test.use({ route: '/chat' });
 * - For /knowledge route: test.use({ route: '/knowledge' });
 */
export const test = base.extend<TestFixtures>({
  // Route option - allows tests to specify which route to launch
  route: ["", { option: true }],

  // Auto-navigate to the specified route before each test
  page: async ({ page, route }, use) => {
    if (route) {
      const baseUrl = process.env.BASE_URL || "http://localhost:3000";
      await page.goto(`${baseUrl}${route}`);
    }
    await use(page);
  },

  // Settings page object
  settings: async ({ page }, use) => {
    const settings = new Settings(page);
    await use(settings);
  },

  // Knowledge page object
  knowledge: async ({ page }, use) => {
    const knowledge = new Knowledge(page);
    await use(knowledge);
  },

  // Chat page object
  chat: async ({ page }, use) => {
    const chat = new Chat(page);
    await use(chat);
  },

  // Cleanup utility for documents
  cleanupDocuments: async ({ knowledge }, use) => {
    const documentsToCleanup: string[] = [];

    // Provide the cleanup function to the test
    const cleanup = async (documentNames: string[]) => {
      documentsToCleanup.push(...documentNames);
    };

    await use(cleanup);

    // After test: cleanup all registered documents using bulk delete
    if (documentsToCleanup.length > 0) {
      try {
        const result = await knowledge.deleteDocument(documentsToCleanup);
        if (typeof result === "object") {
          if (result.found.length > 0) {
            logger.info(`✓ Cleaned up ${result.found.length} document(s)`);
          }
          if (result.notFound.length > 0) {
            logger.info(
              `ℹ️  ${result.notFound.length} document(s) not found (already deleted)`,
            );
          }
        }
      } catch (error) {
        logger.warn(`⚠ Failed to cleanup documents:`, error);
      }
    }
  },

  // Skip beforeEach fixture - allows tests to control navigation
  skipBeforeEach: [false, { option: true }],
});

export { expect } from "@playwright/test";
