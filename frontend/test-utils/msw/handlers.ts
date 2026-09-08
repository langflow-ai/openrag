import { HttpResponse, http } from "msw";
import type { TasksResponse } from "@/app/api/queries/useGetTasksQuery";

/**
 * Default handlers, shared by every test.
 *
 * Paths are RELATIVE and match what the app actually calls. Every browser-side
 * request goes through the catch-all proxy at `app/api/[...path]/route.ts`, so
 * `/api/*` covers the whole surface. MSW resolves relative paths against
 * `location.origin`, which vitest.config.mts pins to http://localhost:3000 via
 * `environmentOptions.jsdom.url`.
 *
 * Keep this list minimal: only endpoints many tests need in a boring happy-path
 * shape. Anything test-specific belongs in that test via `server.use(...)`,
 * which setup.ts resets after every test.
 *
 * ── On typing (see R4 in local/plans/frontend-testing-foundation.md) ─────────
 * Handler bodies are annotated with the frontend's own exported response
 * interfaces. This catches drift between a handler and what the app believes
 * the API returns — a change to `TasksResponse` breaks `npm run typecheck`
 * here.
 *
 * It does NOT catch backend drift. The original plan was to generate these
 * types from the backend's /openapi.json, but 122 of 140 operations declare
 * `"schema": {}` because the FastAPI routes have no `response_model`, so the
 * generated types would be `unknown` almost everywhere. Typing against
 * frontend interfaces is the honest subset of that idea; detecting real
 * backend drift needs either `response_model` on the backend routes or a
 * separate contract test against a live stack.
 */

const emptyTasks: TasksResponse = { tasks: [] };

export const handlers = [
  http.get("/api/tasks/enhanced", () => HttpResponse.json(emptyTasks)),
];
