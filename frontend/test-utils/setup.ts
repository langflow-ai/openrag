/**
 * Global Vitest setup. Wired via `setupFiles` in vitest.config.mts, so it runs
 * once per test file before any test.
 *
 * Two jobs: register jest-dom matchers, and polyfill the browser APIs jsdom
 * does not implement.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { server } from "./msw/server";

// RTL auto-cleans when it detects a global afterEach, but we register it
// explicitly so behaviour does not silently change if `globals` is turned off.
afterEach(() => {
  cleanup();
});

// `onUnhandledRequest: "error"` makes an unmocked call fail loudly and
// immediately. Without it a missing handler surfaces as a mystery timeout.
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

// Drops per-test `server.use(...)` overrides so tests cannot leak into each
// other through the handler list.
afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

// jsdom has no layout engine and ships none of the observer APIs. Components
// that merely *call* these can be tested; components whose behaviour depends on
// real geometry (ag-grid virtualization, use-stick-to-bottom) cannot, and
// belong in Playwright instead. See R3 in
// local/plans/frontend-testing-foundation.md.

if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated, still called by some libs
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

class MockObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn(() => []);
  root = null;
  rootMargin = "";
  thresholds = [];
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver =
    MockObserver as unknown as typeof globalThis.ResizeObserver;
}

if (!globalThis.IntersectionObserver) {
  globalThis.IntersectionObserver =
    MockObserver as unknown as typeof globalThis.IntersectionObserver;
}

// Not implemented by jsdom; Radix calls it when moving focus between items.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

// Radix primitives measure with these; jsdom returns undefined rather than 0.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = vi.fn(() => false);
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = vi.fn();
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = vi.fn();
}
