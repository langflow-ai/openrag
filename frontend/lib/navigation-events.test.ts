import assert from "node:assert/strict";
import { describe, it } from "node:test";
// Node's built-in TypeScript runner requires the extension; tsc resolves the same source.
// @ts-expect-error TS5097
import { getInterceptedNavigationHref } from "./navigation-events.ts";

const currentHref = "http://localhost:3000/settings/agent";

describe("getInterceptedNavigationHref", () => {
  it("intercepts an ordinary click to the settings index", () => {
    assert.equal(
      getInterceptedNavigationHref({
        button: 0,
        href: "/settings",
        currentHref,
      }),
      "/settings",
    );
  });

  it("intercepts an ordinary click to another settings tab", () => {
    assert.equal(
      getInterceptedNavigationHref({
        button: 0,
        href: "/settings/ingestion",
        currentHref,
      }),
      "/settings/ingestion",
    );
  });

  for (const modifier of [
    "metaKey",
    "ctrlKey",
    "shiftKey",
    "altKey",
  ] as const) {
    it(`preserves clicks using ${modifier}`, () => {
      assert.equal(
        getInterceptedNavigationHref({
          button: 0,
          href: "/settings/ingestion",
          currentHref,
          [modifier]: true,
        }),
        null,
      );
    });
  }

  it("preserves middle clicks", () => {
    assert.equal(
      getInterceptedNavigationHref({
        button: 1,
        href: "/settings/ingestion",
        currentHref,
      }),
      null,
    );
  });

  it("preserves links that open a new browsing context", () => {
    assert.equal(
      getInterceptedNavigationHref({
        button: 0,
        href: "/settings/ingestion",
        currentHref,
        target: "_blank",
      }),
      null,
    );
  });

  it("leaves external and same-document links to the browser", () => {
    assert.equal(
      getInterceptedNavigationHref({
        button: 0,
        href: "https://example.com/settings",
        currentHref,
      }),
      null,
    );
    assert.equal(
      getInterceptedNavigationHref({
        button: 0,
        href: `${currentHref}#agent-card`,
        currentHref,
      }),
      null,
    );
  });
});
