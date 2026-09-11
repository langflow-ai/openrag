import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { getGreetingMessage } from "./greeting.ts";
import { resolveDisplayName } from "./user.ts";

// ---------------------------------------------------------------------------
// Helpers to control Date and Math.random without a mocking framework
// ---------------------------------------------------------------------------

const _OriginalDate = globalThis.Date;

function fakeDate(hour: number, dayOfWeek: number): void {
  const RealDate = _OriginalDate;
  // @ts-ignore — intentional global override for tests
  globalThis.Date = class extends RealDate {
    getHours() {
      return hour;
    }
    getDay() {
      return dayOfWeek;
    }
  };
}

function restoreDate(): void {
  globalThis.Date = _OriginalDate;
}

let _savedRandom: () => number;

function forceRandom(value: number): void {
  _savedRandom = Math.random;
  Math.random = () => value;
}

function restoreRandom(): void {
  if (_savedRandom) Math.random = _savedRandom;
}

// ---------------------------------------------------------------------------
// getGreetingMessage
// ---------------------------------------------------------------------------

describe("getGreetingMessage", () => {
  afterEach(() => {
    restoreDate();
    restoreRandom();
  });

  it("returns a non-empty string for an anonymous user", () => {
    const msg = getGreetingMessage();
    assert.ok(msg.length > 0, "greeting must not be empty");
  });

  it("returns a non-empty string when passed null", () => {
    const msg = getGreetingMessage(null);
    assert.ok(msg.length > 0);
  });

  it("includes first name as ', Name' when displayName is provided", () => {
    forceRandom(0.9); // force time-slot path (avoid day-of-week branch)
    fakeDate(9, 1); // 09:00 Monday → morning slot
    const msg = getGreetingMessage("Alice Smith");
    assert.ok(msg.includes(", Alice"), `expected ', Alice' in: ${msg}`);
  });

  it("does not include a comma-name fragment for empty string", () => {
    forceRandom(0.9);
    fakeDate(9, 1);
    const msg = getGreetingMessage("");
    // No ', ' insertion — the {name} slot should be blank
    assert.ok(!msg.includes(", "), `unexpected name in: ${msg}`);
  });

  it("uses only the first word of a multi-word name", () => {
    forceRandom(0.9);
    fakeDate(9, 1);
    const msg = getGreetingMessage("Bob Marley");
    assert.ok(msg.includes(", Bob"), `expected ', Bob' in: ${msg}`);
    assert.ok(!msg.includes("Marley"), `unexpected 'Marley' in: ${msg}`);
  });

  it("strips surrounding whitespace from the name", () => {
    forceRandom(0.9);
    fakeDate(9, 1);
    const msg = getGreetingMessage("  Carol  ");
    assert.ok(msg.includes(", Carol"), `expected ', Carol' in: ${msg}`);
  });

  // Time-slot routing
  it("produces a morning greeting between 06:00 and 11:59", () => {
    forceRandom(0.9); // suppress day-of-week branch
    for (const hour of [6, 9, 11]) {
      fakeDate(hour, 1);
      const msg = getGreetingMessage();
      assert.ok(
        /morning|Morning/i.test(msg),
        `expected morning greeting at ${hour}h, got: ${msg}`,
      );
    }
  });

  it("produces an afternoon greeting between 12:00 and 17:59", () => {
    forceRandom(0.9);
    for (const hour of [12, 15, 17]) {
      fakeDate(hour, 1);
      const msg = getGreetingMessage();
      assert.ok(
        /afternoon|Afternoon/i.test(msg),
        `expected afternoon greeting at ${hour}h, got: ${msg}`,
      );
    }
  });

  it("produces an evening greeting between 18:00 and 23:59", () => {
    forceRandom(0.9);
    for (const hour of [18, 21, 23]) {
      fakeDate(hour, 1);
      const msg = getGreetingMessage();
      assert.ok(
        /evening|Evening/i.test(msg),
        `expected evening greeting at ${hour}h, got: ${msg}`,
      );
    }
  });

  it("produces a late-night greeting between 00:00 and 05:59", () => {
    forceRandom(0.9);
    for (const hour of [0, 2, 5]) {
      fakeDate(hour, 1);
      const msg = getGreetingMessage();
      assert.ok(
        /hey|late night|working late|still up/i.test(msg),
        `expected late-night greeting at ${hour}h, got: ${msg}`,
      );
    }
  });

  // Day-of-week branch
  it("can produce a day-of-week greeting when Math.random < 0.35", () => {
    forceRandom(0); // 0 < 0.35 → always take day branch
    fakeDate(9, 5); // Friday
    const msg = getGreetingMessage();
    assert.ok(
      /friday|tgif/i.test(msg),
      `expected Friday greeting, got: ${msg}`,
    );
  });

  it("skips day-of-week greeting when Math.random >= 0.35", () => {
    forceRandom(0.9); // 0.9 >= 0.35 → always skip day branch
    fakeDate(9, 5); // Friday morning
    const msg = getGreetingMessage();
    assert.ok(
      /morning|Morning/i.test(msg),
      `expected morning greeting (day branch suppressed), got: ${msg}`,
    );
  });
});

// ---------------------------------------------------------------------------
// resolveDisplayName
// ---------------------------------------------------------------------------

describe("resolveDisplayName", () => {
  it("returns null for null input", () => {
    assert.equal(resolveDisplayName(null), null);
  });

  it("returns null for undefined input", () => {
    assert.equal(resolveDisplayName(undefined), null);
  });

  it("returns null when both fields are absent", () => {
    assert.equal(resolveDisplayName({}), null);
  });

  it("returns display_name when set", () => {
    assert.equal(
      resolveDisplayName({ display_name: "Alice", name: "Alice Smith" }),
      "Alice",
    );
  });

  it("falls back to name when display_name is absent", () => {
    assert.equal(resolveDisplayName({ name: "Bob" }), "Bob");
  });

  it("falls back to name when display_name is null", () => {
    assert.equal(
      resolveDisplayName({ display_name: null, name: "Carol" }),
      "Carol",
    );
  });

  it("falls back to name when display_name is empty string", () => {
    // Empty string is falsy — should fall through to name
    assert.equal(
      resolveDisplayName({ display_name: "", name: "Dave" }),
      "Dave",
    );
  });

  it("ignores the 'Anonymous User' sentinel and returns null", () => {
    assert.equal(
      resolveDisplayName({ display_name: null, name: "Anonymous User" }),
      null,
    );
  });

  it("prefers display_name over name even when name is 'Anonymous User'", () => {
    assert.equal(
      resolveDisplayName({ display_name: "Eve", name: "Anonymous User" }),
      "Eve",
    );
  });

  it("returns null when name is null and display_name is absent", () => {
    assert.equal(resolveDisplayName({ name: null }), null);
  });
});
