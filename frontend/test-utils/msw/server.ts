import { setupServer } from "msw/node";
import { handlers } from "./handlers";

/**
 * The MSW server, shared across the whole Vitest run.
 *
 * Intercepts below the app: the code under test keeps using real `fetch`, real
 * `Response` objects, and the real react-query cache. Nothing in
 * `app/api/queries/` or `app/api/mutations/` is mocked away, so the URL, the
 * `response.ok` branch, the payload shape, and the query wiring all stay under
 * test. See R4 in local/plans/frontend-testing-foundation.md.
 *
 * Lifecycle is registered in test-utils/setup.ts.
 */
export const server = setupServer(...handlers);
