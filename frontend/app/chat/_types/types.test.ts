import assert from "node:assert/strict";
import { describe, it } from "vitest";
import { makeInitialMessage } from "./types";

describe("makeInitialMessage", () => {
  it("returns an assistant message with a non-empty greeting", () => {
    const msg = makeInitialMessage();
    assert.equal(msg.role, "assistant");
    assert.ok(msg.content.length > 0, "content must not be empty");
    assert.ok(msg.timestamp instanceof Date, "timestamp must be a Date");
  });

  it("includes the display name in the greeting when provided", () => {
    const msg = makeInitialMessage("Alice");
    assert.ok(
      msg.content.includes("Alice"),
      `expected 'Alice' in greeting: ${msg.content}`,
    );
  });

  it("produces a generic greeting when displayName is null", () => {
    const msg = makeInitialMessage(null);
    assert.equal(msg.role, "assistant");
    assert.ok(msg.content.length > 0);
    // No comma-name insertion when no name is given
    assert.ok(
      !msg.content.includes(", null"),
      `unexpected literal 'null' in: ${msg.content}`,
    );
  });

  it("produces a generic greeting when displayName is omitted", () => {
    const msg = makeInitialMessage();
    assert.ok(msg.content.length > 0);
  });
});
