import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { saveDisplayName } from "./onboarding-personalization.helpers.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeResolvedMutate() {
  const calls: Array<{ display_name: string | null }> = [];
  return {
    calls,
    mutateAsync: async (vars: { display_name: string | null }) => {
      calls.push(vars);
    },
  };
}

function makeRejectedMutate(error = new Error("network error")) {
  return async (_vars: { display_name: string | null }) => {
    throw error;
  };
}

function makeRefresh(shouldThrow = false) {
  const calls: number[] = [];
  return {
    calls,
    refreshAuth: async () => {
      calls.push(1);
      if (shouldThrow) throw new Error("refresh failed");
    },
  };
}

function makeTracker() {
  const calls: string[] = [];
  // Accepts an optional message so it satisfies both `() => void`
  // (onComplete) and `(msg: string) => void` (onError) signatures.
  return {
    calls,
    fn: (msg?: string) => {
      calls.push(msg ?? "");
    },
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("onboarding saveDisplayName — success path", () => {
  it("trims the value and passes it to mutateAsync", async () => {
    const mut = makeResolvedMutate();
    const refresh = makeRefresh();
    const onComplete = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("  Alice  ", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: refresh.refreshAuth,
      onComplete: onComplete.fn,
      onError: onError.fn,
    });

    assert.deepEqual(mut.calls, [{ display_name: "Alice" }]);
    assert.equal(refresh.calls.length, 1, "refreshAuth must be called");
    assert.equal(onComplete.calls.length, 1, "onComplete must be called");
    assert.equal(onError.calls.length, 0, "onError must not be called");
  });

  it("converts whitespace-only input to null payload", async () => {
    const mut = makeResolvedMutate();
    const refresh = makeRefresh();
    const onComplete = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("   ", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: refresh.refreshAuth,
      onComplete: onComplete.fn,
      onError: onError.fn,
    });

    assert.deepEqual(mut.calls, [{ display_name: null }]);
    assert.equal(onComplete.calls.length, 1);
    assert.equal(onError.calls.length, 0);
  });

  it("converts empty string to null payload", async () => {
    const mut = makeResolvedMutate();
    const refresh = makeRefresh();
    const onComplete = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: refresh.refreshAuth,
      onComplete: onComplete.fn,
      onError: onError.fn,
    });

    assert.deepEqual(mut.calls, [{ display_name: null }]);
    assert.equal(onComplete.calls.length, 1);
  });
});

describe("onboarding saveDisplayName — failure path", () => {
  it("calls onError and skips refreshAuth + onComplete when mutateAsync rejects", async () => {
    const refresh = makeRefresh();
    const onComplete = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("Alice", {
      mutateAsync: makeRejectedMutate(),
      refreshAuth: refresh.refreshAuth,
      onComplete: onComplete.fn,
      onError: onError.fn,
    });

    assert.equal(onError.calls.length, 1, "onError must be called");
    assert.ok(
      onError.calls[0].includes("Failed to save"),
      `unexpected error message: ${onError.calls[0]}`,
    );
    assert.equal(refresh.calls.length, 0, "refreshAuth must not be called");
    assert.equal(onComplete.calls.length, 0, "onComplete must not be called");
  });

  it("calls onError and skips onComplete when refreshAuth rejects", async () => {
    const mut = makeResolvedMutate();
    const refresh = makeRefresh(true);
    const onComplete = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("Alice", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: refresh.refreshAuth,
      onComplete: onComplete.fn,
      onError: onError.fn,
    });

    assert.equal(
      onError.calls.length,
      1,
      "onError must fire when refreshAuth throws",
    );
    assert.equal(
      onComplete.calls.length,
      0,
      "onComplete must not fire when refreshAuth throws",
    );
  });
});
