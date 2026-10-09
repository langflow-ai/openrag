"use client";

import React, {
  createContext,
  ReactNode,
  use,
  useCallback,
  useEffect,
  useState,
} from "react";
import { apiClient } from "@/lib/api-client";
import { hasRbacPermission } from "@/lib/brand";
import type { RunMode } from "@/lib/constants";
import { frontendUrl } from "@/lib/frontend-base-path";
import { encodeBase64 } from "@/lib/utils";

export interface User {
  user_id: string;
  email: string;
  name: string;
  picture?: string;
  provider: string;
  last_login?: string;
  roles?: string[];
  permissions?: string[];
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isNoAuthMode: boolean;
  isIbmAuthMode: boolean;
  runMode: RunMode | null;
  version: string | null;
  permissions: Set<string>;
  roles: string[];
  /**
   * Whether the backend is enforcing RBAC (mirrors `OPENRAG_RBAC_ENFORCE`).
   * When false, the system behaves like the pre-RBAC release: any
   * authenticated user has full access. The UI hides RBAC-only
   * sections (Users & Roles, audit log, role pills) so the experience
   * matches the backend behavior.
   */
  rbacEnforced: boolean;
  /** SaaS/cloud context from backend (connector policy, gated settings). */
  cloudContext: boolean;
  /** False until the first /api/users/me permissions fetch finishes. */
  permissionsResolved: boolean;
  /** True iff the workspace has been onboarded. Sourced from the public
   * GET /api/onboarding-status endpoint (no auth needed). */
  isOnboarded: boolean | null;
  /** Current onboarding step indicator (int index or named step). */
  onboardingStep: number | string | null;
  can: (perm: string) => boolean;
  login: () => void;
  loginWithIbm: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshAuth: () => Promise<void>;
  refreshPermissions: () => Promise<void>;
  refreshOnboardingStatus: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function useAuth() {
  const context = use(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isNoAuthMode, setIsNoAuthMode] = useState(false);
  const [isIbmAuthMode, setIsIbmAuthMode] = useState(false);
  const [version, setVersion] = useState<string | null>(null);
  const [runMode, setRunMode] = useState<RunMode | null>(null);

  const checkAuth = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await apiClient.get("/auth/me");

      // If we can't reach the backend, keep loading
      if (response.status === 0 || response.status >= 500) {
        setTimeout(checkAuth, 2000);
        return;
      }

      const data = response.data;
      if (data.version) setVersion(data.version);
      if (data.run_mode) setRunMode(data.run_mode);

      // Check auth mode flags
      if (data.ibm_auth_mode) {
        setIsIbmAuthMode(true);
        setIsNoAuthMode(false);
        setUser(data.authenticated && data.user ? data.user : null);
      } else if (data.no_auth_mode) {
        setIsNoAuthMode(true);
        setIsIbmAuthMode(false);
        // No-auth mode is always anonymous — no user identity.
        setUser(null);
      } else if (data.authenticated && data.user) {
        setIsNoAuthMode(false);
        setIsIbmAuthMode(false);
        setUser(data.user);
      } else {
        setIsNoAuthMode(false);
        setIsIbmAuthMode(false);
        setUser(null);
      }

      setIsLoading(false);
    } catch (error) {
      console.error("Auth check failed:", error);
      setTimeout(checkAuth, 2000);
    }
  }, []);

  const login = () => {
    // Don't allow login in no-auth mode or IBM auth mode
    if (isNoAuthMode) {
      return;
    }
    if (isIbmAuthMode) {
      return;
    }

    // Use the correct auth callback URL, not connectors callback
    const redirectUri = frontendUrl("/auth/callback");

    apiClient
      .post("/auth/init", {
        connector_type: "google_drive",
        purpose: "app_auth",
        name: "App Authentication",
        redirect_uri: redirectUri,
      })
      .then((response) => response.data)
      .then((result) => {
        if (result.oauth_config) {
          // Store that this is for app authentication
          localStorage.setItem("auth_purpose", "app_auth");
          localStorage.setItem("connecting_connector_id", result.connection_id);
          localStorage.setItem("connecting_connector_type", "app_auth");
          localStorage.setItem("auth_redirect_to", window.location.pathname);

          const state = isIbmAuthMode
            ? encodeBase64(
                `id=${result.connection_id}&return=${frontendUrl("/auth/callback")}`,
              )
            : result.connection_id;

          const authUrl =
            `${result.oauth_config.authorization_endpoint}?` +
            `client_id=${result.oauth_config.client_id}&` +
            `response_type=code&` +
            `scope=${result.oauth_config.scopes.join(" ")}&` +
            `redirect_uri=${encodeURIComponent(result.oauth_config.redirect_uri)}&` +
            `access_type=offline&` +
            `prompt=${result.oauth_config.prompt ?? "consent"}&` +
            `state=${encodeURIComponent(state)}`;
          window.location.href = authUrl;
        } else {
          console.error("No oauth_config in response:", result);
        }
      })
      .catch((error) => {
        console.error("Login failed:", error);
      });
  };

  const loginWithIbm = async (username: string, password: string) => {
    const response = await apiClient.post("/auth/ibm/login", undefined, {
      headers: {
        Authorization: "Basic " + btoa(username + ":" + password),
      },
    });
    if (response.status < 200 || response.status >= 300) {
      const data = response.data || {};
      throw new Error(data.detail || "Login failed");
    }
    await checkAuth();
  };

  const logout = async () => {
    if (isNoAuthMode) {
      return;
    }

    try {
      await apiClient.post("/auth/logout");
      setUser(null);
    } catch (error) {
      console.error("Logout failed:", error);
    }
  };

  const refreshAuth = useCallback(async () => {
    await checkAuth();
  }, [checkAuth]);

  const [permissions, setPermissions] = useState<Set<string>>(new Set());
  const [roles, setRoles] = useState<string[]>([]);
  // Default to true so RBAC-only UI doesn't briefly flash on first
  // load before /api/users/me responds. The backend is authoritative;
  // this is just a UI affordance.
  const [rbacEnforced, setRbacEnforced] = useState<boolean>(true);
  const [cloudContext, setCloudContext] = useState<boolean>(false);
  const [permissionsResolved, setPermissionsResolved] =
    useState<boolean>(false);

  const resetPermissionState = useCallback(() => {
    setPermissions(new Set());
    setRoles([]);
    setRbacEnforced(true);
    setCloudContext(false);
  }, []);

  const fetchPermissions = useCallback(async () => {
    try {
      const r = await apiClient.get("/users/me");
      if (r.status < 200 || r.status >= 300) {
        resetPermissionState();
        return;
      }
      const data = r.data;
      const perms: string[] = Array.isArray(data?.permissions)
        ? data.permissions
        : [];
      const userRoles: string[] = Array.isArray(data?.roles) ? data.roles : [];
      setPermissions(new Set(perms));
      setRoles(userRoles);
      // Field is optional from older backends — default to true.
      setRbacEnforced(
        typeof data?.rbac_enforced === "boolean" ? data.rbac_enforced : true,
      );
      setCloudContext(
        typeof data?.cloud_context === "boolean" ? data.cloud_context : false,
      );
    } catch {
      resetPermissionState();
    } finally {
      setPermissionsResolved(true);
    }
  }, [resetPermissionState]);

  const refreshPermissions = useCallback(async () => {
    await fetchPermissions();
  }, [fetchPermissions]);

  // Public onboarding-status — fetched once on mount, no auth required.
  // The frontend uses this to decide between the wizard and the login flow.
  const [isOnboarded, setIsOnboarded] = useState<boolean | null>(null);
  const [onboardingStep, setOnboardingStep] = useState<number | string | null>(
    null,
  );

  const fetchOnboardingStatus = useCallback(async () => {
    try {
      const r = await apiClient.get("/onboarding-status");
      if (r.status < 200 || r.status >= 300) return;
      const data = r.data;
      setIsOnboarded(Boolean(data?.onboarded));
      const step = data?.current_step;
      setOnboardingStep(
        typeof step === "string" || typeof step === "number" ? step : null,
      );
    } catch {
      // Conservative: don't flip the flag if the call fails.
    }
  }, []);

  const refreshOnboardingStatus = useCallback(async () => {
    await fetchOnboardingStatus();
  }, [fetchOnboardingStatus]);

  useEffect(() => {
    fetchOnboardingStatus();
  }, [fetchOnboardingStatus]);

  useEffect(() => {
    if (user || isNoAuthMode || isIbmAuthMode) {
      setPermissionsResolved(false);
      void fetchPermissions();
    } else {
      resetPermissionState();
      setPermissionsResolved(true);
    }
  }, [
    user,
    isNoAuthMode,
    isIbmAuthMode,
    fetchPermissions,
    resetPermissionState,
  ]);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const can = useCallback(
    (perm: string): boolean =>
      hasRbacPermission(perm, { isNoAuthMode, rbacEnforced, permissions }),
    [permissions, isNoAuthMode, rbacEnforced],
  );

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user,
    isNoAuthMode,
    isIbmAuthMode,
    runMode,
    version,
    permissions,
    roles,
    rbacEnforced,
    cloudContext,
    permissionsResolved,
    isOnboarded,
    onboardingStep,
    can,
    login,
    loginWithIbm,
    logout,
    refreshAuth,
    refreshPermissions,
    refreshOnboardingStatus,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
