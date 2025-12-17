/**
 * Integration tests for OpenRAG TypeScript SDK.
 *
 * These tests run against a real OpenRAG instance.
 * Requires: OPENRAG_URL environment variable (defaults to http://localhost:8000)
 *
 * Run with: npm test
 */

import { describe, it, expect, beforeAll } from "vitest";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";

// Dynamic import to handle the SDK not being built yet
let OpenRAGClient: typeof import("../src").OpenRAGClient;

const BASE_URL = process.env.OPENRAG_URL || "http://localhost:8000";
const SKIP_TESTS = process.env.SKIP_SDK_INTEGRATION_TESTS === "true";

// Create API key for tests
async function createApiKey(): Promise<string> {
  const response = await fetch(`${BASE_URL}/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "TypeScript SDK Integration Test" }),
  });

  if (response.status === 401) {
    throw new Error("Cannot create API key - authentication required");
  }

  if (!response.ok) {
    throw new Error(`Failed to create API key: ${await response.text()}`);
  }

  const data = await response.json();
  return data.api_key;
}

// Create test file
function createTestFile(): string {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sdk-test-"));
  const filePath = path.join(tmpDir, "sdk_test_doc.md");
  fs.writeFileSync(
    filePath,
    "# SDK Integration Test Document\n\n" +
      "This document tests the OpenRAG TypeScript SDK.\n" +
      "It contains unique content about orange kangaroos jumping.\n"
  );
  return filePath;
}

describe.skipIf(SKIP_TESTS)("OpenRAG TypeScript SDK Integration", () => {
  let client: InstanceType<typeof OpenRAGClient>;
  let testFilePath: string;

  beforeAll(async () => {
    // Import SDK
    const sdk = await import("../src");
    OpenRAGClient = sdk.OpenRAGClient;

    // Create API key and client
    const apiKey = await createApiKey();
    client = new OpenRAGClient({ apiKey, baseUrl: BASE_URL });

    // Create test file
    testFilePath = createTestFile();
  });

  describe("Settings", () => {
    it("should get settings", async () => {
      const settings = await client.settings.get();

      expect(settings.agent).toBeDefined();
      expect(settings.knowledge).toBeDefined();
    });
  });

  describe("Documents", () => {
    it("should ingest a document (wait for completion)", async () => {
      // wait=true (default) polls until completion
      const result = await client.documents.ingest({ filePath: testFilePath });

      expect(result.status).toBe("completed");
      expect((result as any).successful_files).toBeGreaterThanOrEqual(1);
    });

    it("should ingest a document without waiting", async () => {
      // wait=false returns immediately with task_id
      const result = await client.documents.ingest({
        filePath: testFilePath,
        wait: false,
      });

      expect((result as any).task_id).toBeDefined();

      // Can poll manually
      const finalStatus = await client.documents.waitForTask(
        (result as any).task_id
      );
      expect(finalStatus.status).toBe("completed");
    });

    it("should delete a document", async () => {
      // First ingest (wait for completion)
      await client.documents.ingest({ filePath: testFilePath });

      // Then delete
      const result = await client.documents.delete(path.basename(testFilePath));

      expect(result.success).toBe(true);
    });
  });

  describe("Search", () => {
    it("should search documents", async () => {
      // Documents already ingested by previous tests
      const results = await client.search.query("orange kangaroos jumping");

      expect(results.results).toBeDefined();
      expect(Array.isArray(results.results)).toBe(true);
    });
  });

  describe("Chat", () => {
    it("should send non-streaming chat", async () => {
      const response = await client.chat.create({
        message: "Say hello in exactly 3 words.",
      });

      expect(response.response).toBeDefined();
      expect(typeof response.response).toBe("string");
      expect(response.response.length).toBeGreaterThan(0);
    });

    it("should stream chat with create({ stream: true })", async () => {
      let collectedText = "";

      for await (const event of await client.chat.create({
        message: "Say 'test' and nothing else.",
        stream: true,
      })) {
        if (event.type === "content") {
          collectedText += event.delta;
        }
      }

      expect(collectedText.length).toBeGreaterThan(0);
    });

    it("should stream chat with stream() context manager", async () => {
      const stream = await client.chat.stream({
        message: "Say 'hello' and nothing else.",
      });

      try {
        for await (const _ of stream) {
          // Consume stream
        }

        expect(stream.text.length).toBeGreaterThan(0);
      } finally {
        stream.close();
      }
    });

    it("should use textStream helper", async () => {
      let collected = "";

      const stream = await client.chat.stream({
        message: "Say 'world' and nothing else.",
      });

      try {
        for await (const text of stream.textStream) {
          collected += text;
        }

        expect(collected.length).toBeGreaterThan(0);
      } finally {
        stream.close();
      }
    });

    it("should use finalText() helper", async () => {
      const stream = await client.chat.stream({
        message: "Say 'done' and nothing else.",
      });

      try {
        const text = await stream.finalText();
        expect(text.length).toBeGreaterThan(0);
      } finally {
        stream.close();
      }
    });

    it("should continue a conversation", async () => {
      // First message
      const response1 = await client.chat.create({
        message: "Remember the number 99.",
      });
      expect(response1.chatId).toBeDefined();

      // Continue conversation
      const response2 = await client.chat.create({
        message: "What number did I ask you to remember?",
        chatId: response1.chatId!,
      });
      expect(response2.response).toBeDefined();
    });

    it("should list conversations", async () => {
      // Create a conversation first
      await client.chat.create({ message: "Test message for listing." });

      // List conversations
      const result = await client.chat.list();

      expect(result.conversations).toBeDefined();
      expect(Array.isArray(result.conversations)).toBe(true);
    });
  });
});
