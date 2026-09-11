import assert from "node:assert/strict";
import { describe, it } from "vitest";
import { saveDisplayName } from "./general-tab.helpers.ts";

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
  return { calls, fn: (msg: string) => calls.push(msg) };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("general-tab saveDisplayName — success path", () => {
  it("trims the value and passes it to mutateAsync", async () => {
    const mut = makeResolvedMutate();
    const refresh = makeRefresh();
    const onSuccess = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("  Bob  ", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: refresh.refreshAuth,
      onSuccess: onSuccess.fn,
      onError: onError.fn,
    });

    assert.deepEqual(mut.calls, [{ display_name: "Bob" }]);
    assert.equal(refresh.calls.length, 1, "refreshAuth must be called");
    assert.equal(onSuccess.calls.length, 1, "onSuccess must be called");
    assert.ok(
      onSuccess.calls[0].includes("updated"),
      `unexpected success message: ${onSuccess.calls[0]}`,
    );
    assert.equal(onError.calls.length, 0, "onError must not be called");
  });

  it("converts whitespace-only input to null payload", async () => {
    const mut = makeResolvedMutate();
    const refresh = makeRefresh();
    const onSuccess = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("   ", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: refresh.refreshAuth,
      onSuccess: onSuccess.fn,
      onError: onError.fn,
    });

    assert.deepEqual(mut.calls, [{ display_name: null }]);
    assert.equal(onSuccess.calls.length, 1);
    assert.equal(onError.calls.length, 0);
  });

  it("converts empty string to null payload", async () => {
    const mut = makeResolvedMutate();
    const refresh = makeRefresh();
    const onSuccess = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: refresh.refreshAuth,
      onSuccess: onSuccess.fn,
      onError: onError.fn,
    });

    assert.deepEqual(mut.calls, [{ display_name: null }]);
    assert.equal(onSuccess.calls.length, 1);
  });
});

describe("general-tab saveDisplayName — failure path", () => {
  it("calls onError and skips refreshAuth + onSuccess when mutateAsync rejects", async () => {
    const refresh = makeRefresh();
    const onSuccess = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("Bob", {
      mutateAsync: makeRejectedMutate(),
      refreshAuth: refresh.refreshAuth,
      onSuccess: onSuccess.fn,
      onError: onError.fn,
    });

    assert.equal(onError.calls.length, 1, "onError must be called");
    assert.ok(
      onError.calls[0].includes("Failed to update"),
      `unexpected error message: ${onError.calls[0]}`,
    );
    assert.equal(refresh.calls.length, 0, "refreshAuth must not be called");
    assert.equal(onSuccess.calls.length, 0, "onSuccess must not be called");
  });

  it("calls onError and skips onSuccess when refreshAuth rejects", async () => {
    const mut = makeResolvedMutate();
    const refresh = makeRefresh(true);
    const onSuccess = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("Bob", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: refresh.refreshAuth,
      onSuccess: onSuccess.fn,
      onError: onError.fn,
    });

    assert.equal(
      onError.calls.length,
      1,
      "onError must fire when refreshAuth throws",
    );
    assert.equal(
      onSuccess.calls.length,
      0,
      "onSuccess must not fire when refreshAuth throws",
    );
  });
});

describe("general-tab saveDisplayName — onSaved callback", () => {
  it("calls onSaved with trimmed canonical before refreshAuth", async () => {
    const order: string[] = [];
    const mut = makeResolvedMutate();
    const { refreshAuth } = makeRefresh();
    const onSuccess = makeTracker();
    const onError = makeTracker();

    const deps = {
      mutateAsync: mut.mutateAsync,
      refreshAuth: async () => {
        order.push("refresh");
      },
      onSaved: (canonical: string | null) => {
        order.push(`saved:${canonical}`);
      },
      onSuccess: onSuccess.fn,
      onError: onError.fn,
    };

    await saveDisplayName("  Bob  ", deps);

    assert.deepEqual(
      order,
      ["saved:Bob", "refresh"],
      "onSaved must fire after mutate and before refreshAuth",
    );
    assert.equal(onError.calls.length, 0);
  });

  it("calls onSaved with null for whitespace-only input", async () => {
    const mut = makeResolvedMutate();
    const { refreshAuth } = makeRefresh();
    const saved: Array<string | null> = [];

    await saveDisplayName("   ", {
      mutateAsync: mut.mutateAsync,
      refreshAuth,
      onSaved: (c) => saved.push(c),
      onSuccess: makeTracker().fn,
      onError: makeTracker().fn,
    });

    assert.deepEqual(saved, [null]);
  });

  it("does not call onSaved when mutateAsync rejects", async () => {
    const { refreshAuth } = makeRefresh();
    const saved: Array<string | null> = [];

    await saveDisplayName("Bob", {
      mutateAsync: makeRejectedMutate(),
      refreshAuth,
      onSaved: (c) => saved.push(c),
      onSuccess: makeTracker().fn,
      onError: makeTracker().fn,
    });

    assert.equal(saved.length, 0, "onSaved must not fire on failure");
  });

  it("does not call onSaved when refreshAuth rejects", async () => {
    // onSaved fires before refreshAuth, so a refreshAuth failure should
    // still have called onSaved — but onSuccess must NOT fire.
    const mut = makeResolvedMutate();
    const saved: Array<string | null> = [];
    const onSuccess = makeTracker();
    const onError = makeTracker();

    await saveDisplayName("Bob", {
      mutateAsync: mut.mutateAsync,
      refreshAuth: async () => {
        throw new Error("refresh failed");
      },
      onSaved: (c) => saved.push(c),
      onSuccess: onSuccess.fn,
      onError: onError.fn,
    });

    assert.deepEqual(saved, ["Bob"], "onSaved fires before refreshAuth throws");
    assert.equal(onSuccess.calls.length, 0, "onSuccess must not fire");
    assert.equal(onError.calls.length, 1, "onError must fire");
  });
});
