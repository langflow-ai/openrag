/**
 * MSW handlers for the `AuthProvider` boot sequence.
 *
 * `renderWithProviders({ auth })` installs these, so most tests never call
 * this module directly. Reach for `authHandlers()` when you need a scenario
 * active before render — e.g. seeding the query cache — or when asserting on
 * the requests themselves.
 *
 * ── Why these must always answer ────────────────────────────────────────────
 * `checkAuth` in `contexts/auth-context.tsx` reschedules itself via
 * `setTimeout(checkAuth, 2000)` on a 5xx or a thrown fetch. Under
 * `onUnhandledRequest: "error"` an unhandled `/api/auth/me` therefore does not
 * fail the test — it retries forever until the test times out. That is why
 * `handlers.ts` ships a default auth scenario rather than leaving auth
 * unmocked. A test that deliberately exercises the retry path needs
 * `vi.useFakeTimers()`.
 */
import { HttpResponse, http } from "msw";
import type {
  AuthMeResponse,
  AuthScenario,
  OnboardingStatusResponse,
  UsersMeResponse,
} from "@/test-utils/fixtures/auth";

export function authHandlers(scenario: AuthScenario) {
  return [
    http.get("/api/auth/me", () =>
      HttpResponse.json<AuthMeResponse>(scenario.me),
    ),

    // 403 is what the backend returns for an unauthenticated caller, and the
    // branch where the provider clears permissions. `null` in the scenario
    // means exactly that.
    http.get("/api/users/me", () =>
      scenario.usersMe === null
        ? HttpResponse.json({ detail: "Not authenticated" }, { status: 403 })
        : HttpResponse.json<UsersMeResponse>(scenario.usersMe),
    ),

    http.get("/api/onboarding-status", () =>
      HttpResponse.json<OnboardingStatusResponse>(scenario.onboardingStatus),
    ),

    // Not part of boot, but `logout()` calls it and an unhandled POST would
    // surface as an "unhandled request" error rather than a logout assertion.
    http.post("/api/auth/logout", () => HttpResponse.json({ success: true })),
  ];
}
