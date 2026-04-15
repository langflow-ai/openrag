import { defineConfig, devices } from "@playwright/test";
import * as dotenv from "dotenv";
import path from "path";

// Load environment variables from root .env
dotenv.config({ path: path.resolve(__dirname, "..", ".env") });

const PORT = process.env.FRONTEND_PORT || 3000;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  workers: 1,
  reporter: "html",
  timeout: 5 * 60 * 1000,

  use: {
    baseURL: `http://localhost:${PORT}`,
    actionTimeout: 30000,
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  /* Infrastructure (OpenSearch, Langflow, etc.) is expected to be running.
   * Start the backend and frontend servers if not already running. */
  webServer: [
    {
      command: "make backend",
      cwd: path.resolve(__dirname, ".."),
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: true,
      stdout: "pipe",
      stderr: "pipe",
      timeout: 300 * 1000,
    },
    {
      command: "npm run dev",
      port: Number(PORT),
      reuseExistingServer: true,
      env: {
        PORT: String(PORT),
        VITE_PROXY_TARGET:
          process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000",
      },
    },
  ],
});
