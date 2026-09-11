/**
 * `AuthProvider` is the outermost context in `app/layout.tsx` and 33 files call
 * `useAuth()`, so what it resolves to decides what most of the UI renders.
 *
 * Everything here goes through the real provider and real `fetch`; only the
 * three boot endpoints are stubbed, via the shared scenarios in
 * `test-utils/fixtures/auth.ts`. Nothing about the provider is mocked.
 *
 * The cases worth protecting are the ones where "signed in", "allowed", and
 * "has permissions" come apart — no-auth mode grants everything while holding
 * no user, and RBAC-disabled grants everything while holding no permissions.
 * Both look falsy to a naive gate.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http, type RequestHandler } from "msw";
import { describe, expect, it } from "vitest";
import { type User, useAuth } from "@/contexts/auth-context";
import {
  type AuthScenario,
  authPresets,
  makeUser,
  withAuth,
} from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";

/**
 * Mounts the provider under `scenario` and waits out the boot fetches.
 *
 * Gates on `permissionsResolved` rather than `isLoading`: `/api/auth/me`
 * settling only starts the `/api/users/me` fetch, so asserting on permissions
 * after `isLoading` alone is a race.
 */
async function renderAuth(
  scenario: AuthScenario,
  handlers: RequestHandler[] = [],
) {
  const view = renderHook(() => useAuth(), {
    wrapper: createQueryWrapper({
      providers: ["auth"],
      auth: scenario,
      handlers,
    }),
  });

  await waitFor(() => {
    expect(view.result.current.isLoading).toBe(false);
    expect(view.result.current.permissionsResolved).toBe(true);
  });

  return view;
}

describe("AuthProvider", () => {
  it("throws when useAuth is called outside the provider", () => {
    expect(() => renderHook(() => useAuth())).toThrow(
      "useAuth must be used within an AuthProvider",
    );
  });

  describe("a signed-in user", () => {
    it("exposes the user, roles, and granted permissions", async () => {
      const { result } = await renderAuth(authPresets.admin);

      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.user?.email).toBe("tester@example.com");
      expect(result.current.roles).toEqual(["admin"]);
      expect(result.current.can("config:write")).toBe(true);
      expect(result.current.isNoAuthMode).toBe(false);
      expect(result.current.isIbmAuthMode).toBe(false);
    });

    it("reports the version and run mode from /api/auth/me", async () => {
      const { result } = await renderAuth(
        withAuth(authPresets.admin, { me: { run_mode: "oss" } }),
      );

      expect(result.current.version).toBe("1.0.0");
      expect(result.current.runMode).toBe("oss");
    });

    it("denies a permission the user was not granted", async () => {
      const { result } = await renderAuth(authPresets.viewer);

      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.can("config:read")).toBe(true);
      expect(result.current.can("config:write")).toBe(false);
      expect(result.current.can("users:write")).toBe(false);
    });
  });

  describe("no-auth mode", () => {
    // OPENRAG_AUTH_ENABLED=false. The trap: there is no user, so any gate
    // written as `user && can(...)` hides UI that should be fully open.
    it("grants every permission despite holding no user", async () => {
      const { result } = await renderAuth(authPresets.noAuthMode);

      expect(result.current.isNoAuthMode).toBe(true);
      expect(result.current.user).toBeNull();
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.can("config:write")).toBe(true);
      expect(result.current.can("anything:at:all")).toBe(true);
    });
  });

  describe("RBAC disabled", () => {
    // OPENRAG_RBAC_ENFORCE=false — the pre-RBAC release behaviour, where an
    // authenticated user has full access and the permission set stays empty.
    it("grants every permission despite an empty permission set", async () => {
      const { result } = await renderAuth(authPresets.rbacDisabled);

      expect(result.current.rbacEnforced).toBe(false);
      expect(result.current.permissions.size).toBe(0);
      expect(result.current.can("config:write")).toBe(true);
    });

    it("defaults rbacEnforced to true when the backend omits the field", async () => {
      // Older backends do not send `rbac_enforced`. Defaulting to false would
      // silently open RBAC-gated UI against a backend that is enforcing.
      const { result } = await renderAuth(
        withAuth(authPresets.viewer, { usersMe: { rbac_enforced: undefined } }),
      );

      expect(result.current.rbacEnforced).toBe(true);
      expect(result.current.can("config:write")).toBe(false);
    });
  });

  describe("IBM auth mode", () => {
    it("takes precedence and reports cloud context", async () => {
      const { result } = await renderAuth(authPresets.ibmAuthMode);

      expect(result.current.isIbmAuthMode).toBe(true);
      expect(result.current.isNoAuthMode).toBe(false);
      expect(result.current.cloudContext).toBe(true);
      expect(result.current.isAuthenticated).toBe(true);
    });

    it("wins over no_auth_mode when the backend sends both", async () => {
      // The flags are checked in order in `checkAuth`; this pins that order so
      // a reordering does not silently drop a cloud tenant into no-auth mode.
      const { result } = await renderAuth(
        withAuth(authPresets.ibmAuthMode, { me: { no_auth_mode: true } }),
      );

      expect(result.current.isIbmAuthMode).toBe(true);
      expect(result.current.isNoAuthMode).toBe(false);
    });
  });

  describe("unauthenticated", () => {
    it("resolves with no permissions when /api/users/me is refused", async () => {
      const { result } = await renderAuth(authPresets.unauthenticated);

      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.permissions.size).toBe(0);
      expect(result.current.roles).toEqual([]);
      expect(result.current.can("config:read")).toBe(false);
      // Must still flip, or consumers that wait on it hang forever.
      expect(result.current.permissionsResolved).toBe(true);
    });
  });

  describe("onboarding status", () => {
    it("reads onboarded and the current step", async () => {
      const { result } = await renderAuth(
        withAuth(authPresets.admin, {
          onboardingStatus: { onboarded: false, current_step: 2 },
        }),
      );

      expect(result.current.isOnboarded).toBe(false);
      expect(result.current.onboardingStep).toBe(2);
    });

    it("leaves isOnboarded null when the endpoint fails", async () => {
      // Deliberately conservative: a failed status call must not be read as
      // "not onboarded" and bounce a working install into the wizard.
      const { result } = await renderAuth(authPresets.admin, [
        http.get("/api/onboarding-status", () =>
          HttpResponse.json({ detail: "boom" }, { status: 500 }),
        ),
      ]);

      expect(result.current.isOnboarded).toBeNull();
    });
  });

  describe("refreshAuth", () => {
    it("picks up a user who signed in after mount", async () => {
      const { result } = await renderAuth(authPresets.unauthenticated);
      expect(result.current.isAuthenticated).toBe(false);

      const signedIn: User = makeUser({ name: "Signed In" });
      server.use(
        http.get("/api/auth/me", () =>
          HttpResponse.json({ authenticated: true, user: signedIn }),
        ),
        http.get("/api/users/me", () =>
          HttpResponse.json({
            permissions: ["config:read"],
            roles: ["viewer"],
          }),
        ),
      );

      await result.current.refreshAuth();

      await waitFor(() => {
        expect(result.current.user?.name).toBe("Signed In");
        expect(result.current.can("config:read")).toBe(true);
      });
    });
  });

  describe("logout", () => {
    it("clears the user", async () => {
      const { result } = await renderAuth(authPresets.admin);
      expect(result.current.isAuthenticated).toBe(true);

      await result.current.logout();

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(false);
        expect(result.current.user).toBeNull();
      });
    });

    it("is a no-op in no-auth mode", async () => {
      // There is no session to end; calling the endpoint would 404.
      const { result } = await renderAuth(authPresets.noAuthMode);

      await result.current.logout();

      expect(result.current.isNoAuthMode).toBe(true);
      expect(result.current.can("config:write")).toBe(true);
    });
  });
});
