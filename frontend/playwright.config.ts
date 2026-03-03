import { defineConfig, devices } from "@playwright/test";
import * as dotenv from "dotenv";
import path from "path";

// Load test environment variables
dotenv.config({ path: path.resolve(__dirname, ".env.test") });

const PORT = process.env.FRONTEND_PORT || 3000;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  timeout: 5 * 60 * 1000,

  // Setup hook to run before all tests

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

  /* Infrastructure (OpenSearch, Langflow, etc.) is expected to be running already.
   * Only start the backend and frontend servers. */
  webServer: [
    {
      command: "make backend ENV_FILE=frontend/.env.test",
      cwd: path.resolve(__dirname, ".."),
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      stderr: "pipe",
      timeout: 300 * 1000,
      env: {
        // Inherit PATH so make/uv/python are found
        PATH: process.env.PATH || "",
        HOME: process.env.HOME || "",

        // OpenSearch connection
        OPENSEARCH_HOST: process.env.OPENSEARCH_HOST || "localhost",
        OPENSEARCH_PORT: process.env.OPENSEARCH_PORT || "9200",
        OPENSEARCH_USERNAME: process.env.OPENSEARCH_USERNAME || "admin",
        OPENSEARCH_PASSWORD: process.env.OPENSEARCH_PASSWORD || "",
        OPENSEARCH_INDEX_NAME: process.env.OPENSEARCH_INDEX_NAME || "documents",

        // Langflow
        LANGFLOW_URL: process.env.LANGFLOW_URL || "http://localhost:7860",
        LANGFLOW_AUTO_LOGIN: process.env.LANGFLOW_AUTO_LOGIN || "True",
        LANGFLOW_SUPERUSER: process.env.LANGFLOW_SUPERUSER || "",
        LANGFLOW_SUPERUSER_PASSWORD:
          process.env.LANGFLOW_SUPERUSER_PASSWORD || "",
        LANGFLOW_CHAT_FLOW_ID: process.env.LANGFLOW_CHAT_FLOW_ID || "",
        LANGFLOW_INGEST_FLOW_ID: process.env.LANGFLOW_INGEST_FLOW_ID || "",

        // Auth — disable OAuth for E2E
        GOOGLE_OAUTH_CLIENT_ID: "",
        GOOGLE_OAUTH_CLIENT_SECRET: "",

        // Provider API keys
        OPENAI_API_KEY: process.env.OPENAI_API_KEY || "",
        ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || "",
        WATSONX_API_KEY: process.env.WATSONX_API_KEY || "",
        WATSONX_ENDPOINT: process.env.WATSONX_ENDPOINT || "",
        WATSONX_PROJECT_ID: process.env.WATSONX_PROJECT_ID || "",
        OLLAMA_BASE_URL: process.env.OLLAMA_BASE_URL || "",

        // Ingestion
        DISABLE_INGEST_WITH_LANGFLOW:
          process.env.DISABLE_INGEST_WITH_LANGFLOW || "false",
        INGEST_SAMPLE_DATA: process.env.INGEST_SAMPLE_DATA || "true",
      },
    },
    {
      command: "npm run dev",
      port: Number(PORT),
      reuseExistingServer: !process.env.CI,
      env: {
        PORT: String(PORT),
        VITE_PROXY_TARGET:
          process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000",
      },
    },
  ],
});
