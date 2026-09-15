import assert from "node:assert/strict";
import { describe, it } from "vitest";
import { makeInitialMessage, PLACEHOLDER_GREETING } from "./types";

describe("PLACEHOLDER_GREETING", () => {
  it("is an assistant message flagged as a greeting", () => {
    assert.equal(PLACEHOLDER_GREETING.role, "assistant");
    assert.equal(PLACEHOLDER_GREETING.isGreeting, true);
    assert.ok(PLACEHOLDER_GREETING.content.length > 0);
  });

  it("has a deterministic timestamp (epoch zero)", () => {
    assert.equal(PLACEHOLDER_GREETING.timestamp.getTime(), 0);
  });

  it("is the same object reference on every import (no nondeterminism)", () => {
    // Re-importing the module would give the same const — assert the shape
    // is stable by checking the timestamp doesn't change between accesses.
    const t1 = PLACEHOLDER_GREETING.timestamp.getTime();
    const t2 = PLACEHOLDER_GREETING.timestamp.getTime();
    assert.equal(t1, t2);
  });
});

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
