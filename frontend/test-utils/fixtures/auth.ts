/**
 * Fixtures for the auth boot sequence.
 *
 * `AuthProvider` is the outermost context in `app/layout.tsx` and 33 files
 * consume `useAuth()`, so almost every component test starts by deciding who
 * is signed in. That decision is expressed here as an `AuthScenario` — the
 * three payloads the provider fetches on mount — rather than as a fake context
 * value, so the real provider logic (mode precedence, permission resolution,
 * RBAC defaulting) stays under test in every test that uses it.
 *
 * Turn a scenario into MSW handlers with `authHandlers()` from
 * `test-utils/msw/auth.ts`; `renderWithProviders({ auth })` does it for you.
 */
import type { User } from "@/contexts/auth-context";
import type { RunMode } from "@/lib/constants";

/**
 * GET /api/auth/me.
 *
 * Only the fields `checkAuth` in `contexts/auth-context.tsx` actually reads.
 * The mode flags are mutually exclusive in practice and the provider checks
 * them in this order: `ibm_auth_mode`, then `no_auth_mode`, then
 * `authenticated`.
 */
export interface AuthMeResponse {
  authenticated?: boolean;
  user?: User | null;
  no_auth_mode?: boolean;
  ibm_auth_mode?: boolean;
  version?: string;
  run_mode?: RunMode;
}

/** GET /api/users/me — permissions, roles, and the RBAC/cloud flags. */
export interface UsersMeResponse {
  permissions?: string[];
  roles?: string[];
  rbac_enforced?: boolean;
  cloud_context?: boolean;
}

/** GET /api/onboarding-status — public, no auth required. */
export interface OnboardingStatusResponse {
  onboarded?: boolean;
  current_step?: number | string | null;
}

/**
 * The complete boot surface of `AuthProvider`.
 *
 * `usersMe: null` means the endpoint answers 403 — the real shape for a
 * request that is not authenticated, and the branch where the provider resets
 * permission state.
 */
export interface AuthScenario {
  me: AuthMeResponse;
  usersMe: UsersMeResponse | null;
  onboardingStatus: OnboardingStatusResponse;
}

export function makeUser(overrides: Partial<User> = {}): User {
  return {
    user_id: "user-1",
    email: "tester@example.com",
    name: "Test User",
    provider: "google",
    ...overrides,
  };
}

/**
 * Every permission the UI gates on today. `authPresets.admin` grants these, so
 * a test that only needs "a signed-in user who can see everything" does not
 * have to enumerate them.
 */
export const ALL_PERMISSIONS = [
  "config:read",
  "config:write",
  "flows:read",
  "flows:write",
  "connectors:manage:access",
  "users:read",
  "users:write",
  "documents:read",
  "documents:write",
] as const;

function scenario(
  me: AuthMeResponse,
  usersMe: UsersMeResponse | null,
  onboardingStatus: OnboardingStatusResponse = {
    onboarded: true,
    current_step: null,
  },
): AuthScenario {
  return { me, usersMe, onboardingStatus };
}

/**
 * Named starting points, one per branch of `checkAuth`.
 *
 * Compose with `withAuth(preset, { ... })` for one-field variations rather
 * than adding a preset per permutation.
 */
export const authPresets = {
  /** Signed in, RBAC on, every permission granted. */
  admin: scenario(
    { authenticated: true, user: makeUser(), version: "1.0.0" },
    {
      permissions: [...ALL_PERMISSIONS],
      roles: ["admin"],
      rbac_enforced: true,
      cloud_context: false,
    },
  ),

  /** Signed in, RBAC on, read-only. The interesting negative case for gates. */
  viewer: scenario(
    {
      authenticated: true,
      user: makeUser({ user_id: "user-2", name: "View Only" }),
      version: "1.0.0",
    },
    {
      permissions: ["config:read", "flows:read", "documents:read"],
      roles: ["viewer"],
      rbac_enforced: true,
      cloud_context: false,
    },
  ),

  /**
   * OPENRAG_AUTH_ENABLED=false. No user object, but `can()` returns true for
   * everything — the pre-auth release behaviour. A frequent source of gating
   * bugs, because "no user" and "no permissions" both look falsy.
   */
  noAuthMode: scenario(
    { no_auth_mode: true, authenticated: false, version: "1.0.0" },
    { permissions: [], roles: [], rbac_enforced: true, cloud_context: false },
  ),

  /** IBM/SaaS: cloud brand, cloud policy context, signed in. */
  ibmAuthMode: scenario(
    {
      ibm_auth_mode: true,
      authenticated: true,
      user: makeUser({ provider: "ibm" }),
      version: "1.0.0",
    },
    {
      permissions: [...ALL_PERMISSIONS],
      roles: ["admin"],
      rbac_enforced: true,
      cloud_context: true,
    },
  ),

  /** Auth enabled, nobody signed in. `/api/users/me` answers 403. */
  unauthenticated: scenario(
    { authenticated: false, user: null, version: "1.0.0" },
    null,
  ),

  /** Signed in with OPENRAG_RBAC_ENFORCE=false — `can()` is always true. */
  rbacDisabled: scenario(
    { authenticated: true, user: makeUser(), version: "1.0.0" },
    {
      permissions: [],
      roles: [],
      rbac_enforced: false,
      cloud_context: false,
    },
  ),
} satisfies Record<string, AuthScenario>;

export type AuthPresetName = keyof typeof authPresets;

/** Shallow-merges each payload, so a test can vary one field of a preset. */
export function withAuth(
  base: AuthScenario,
  overrides: {
    me?: Partial<AuthMeResponse>;
    usersMe?: Partial<UsersMeResponse> | null;
    onboardingStatus?: Partial<OnboardingStatusResponse>;
  },
): AuthScenario {
  return {
    me: { ...base.me, ...overrides.me },
    usersMe:
      overrides.usersMe === null
        ? null
        : overrides.usersMe
          ? { ...(base.usersMe ?? {}), ...overrides.usersMe }
          : base.usersMe,
    onboardingStatus: {
      ...base.onboardingStatus,
      ...overrides.onboardingStatus,
    },
  };
}
