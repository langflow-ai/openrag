import { HttpResponse, http } from "msw";
import type { Settings } from "@/app/api/queries/useGetSettingsQuery";
import type { TasksResponse } from "@/app/api/queries/useGetTasksQuery";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { authHandlers } from "./auth";

/**
 * Default handlers, shared by every test.
 *
 * Paths are RELATIVE and match what the app actually calls. Every browser-side
 * request goes through the catch-all proxy at `app/api/[...path]/route.ts`, so
 * `/api/*` covers the whole surface. MSW resolves relative paths against
 * `location.origin`, which vitest.config.mts pins to http://localhost:3000 via
 * `environmentOptions.jsdom.url`.
 *
 * ── What belongs here ───────────────────────────────────────────────────────
 * Only the endpoints a *provider* hits on mount. Because `renderWithProviders`
 * mounts the real providers, every one of these is fetched by tests that never
 * mention auth or tasks, and an unmocked one fails the test under
 * `onUnhandledRequest: "error"` (or, for `/api/auth/me`, hangs — see
 * `./auth.ts`). Anything a *component* fetches belongs in that component's
 * test via `renderWithProviders(ui, { handlers })`, which applies them after
 * the auth scenario so they win over it; setup.ts resets them after every
 * test.
 *
 * The default scenario is deliberately the boring one: an admin, RBAC on,
 * onboarding finished, nothing in flight. Tests that care select another via
 * `renderWithProviders({ auth: authPresets.viewer })`.
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
  // AuthProvider: /api/auth/me, /api/users/me, /api/onboarding-status.
  ...authHandlers(authPresets.admin),

  // TaskProvider.
  http.get("/api/tasks/enhanced", () => HttpResponse.json(emptyTasks)),

  // useOnboardingState(), reached through both TaskProvider and ChatProvider.
  http.get("/api/settings", () => HttpResponse.json<Settings>(makeSettings())),
];
