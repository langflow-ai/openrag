/**
 * Shared `next/navigation` test double.
 *
 * 28 files import from `next/navigation` (48 `useRouter`, 14 `usePathname`,
 * 12 `useSearchParams`), and outside a Next app-router tree those hooks throw
 * or return null. Every component test would otherwise open with the same
 * `vi.mock("next/navigation", ...)` block — and each copy would drift.
 *
 * The mock is registered once, globally, in `test-utils/setup.ts`. This module
 * holds the state behind it so a test can drive and assert navigation:
 *
 *   setMockLocation({ pathname: "/knowledge", searchParams: { id: "f1" } });
 *   ...
 *   expect(mockRouter.push).toHaveBeenCalledWith("/chat");
 *
 * `resetMockRouter()` runs in `afterEach`, so state never leaks between tests.
 *
 * Note this is a genuine `vi.mock` — the one place the repo's "mock the
 * network, not the module" rule does not apply, because `next/navigation` is
 * framework plumbing with no network under it to intercept. Navigation that
 * must actually re-render a route belongs in Playwright.
 */
import { vi } from "vitest";

const DEFAULT_PATHNAME = "/";

export const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  prefetch: vi.fn(),
};

let pathname = DEFAULT_PATHNAME;
let searchParams = new URLSearchParams();
let params: Record<string, string | string[]> = {};

export interface MockLocation {
  pathname?: string;
  /** Object form is converted to `URLSearchParams`; a string is parsed. */
  searchParams?: Record<string, string> | string;
  /** Dynamic route segments, for `useParams()`. */
  params?: Record<string, string | string[]>;
}

export function setMockLocation(location: MockLocation) {
  if (location.pathname !== undefined) pathname = location.pathname;
  if (location.searchParams !== undefined) {
    searchParams =
      typeof location.searchParams === "string"
        ? new URLSearchParams(location.searchParams)
        : new URLSearchParams(location.searchParams);
  }
  if (location.params !== undefined) params = location.params;
}

export function resetMockRouter() {
  for (const fn of Object.values(mockRouter)) fn.mockClear();
  pathname = DEFAULT_PATHNAME;
  searchParams = new URLSearchParams();
  params = {};
}

/**
 * The module shape handed to `vi.mock("next/navigation")`.
 *
 * The hooks read the module-level state at call time rather than closing over
 * it, so `setMockLocation` inside a test affects the next render.
 */
export const navigationMock = {
  useRouter: () => mockRouter,
  usePathname: () => pathname,
  useSearchParams: () => searchParams,
  useParams: () => params,
  redirect: vi.fn(),
  notFound: vi.fn(),
};
