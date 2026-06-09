"use client";

import React, {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { hasRbacPermission } from "@/lib/brand";
import { encodeBase64 } from "@/lib/utils";

interface User {
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
  runMode: string | null;
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
  const context = useContext(AuthContext);
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
  const [runMode, setRunMode] = useState<string | null>(null);

  const checkAuth = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/auth/me");

      // If we can't reach the backend, keep loading
      if (!response.ok && (response.status === 0 || response.status >= 500)) {
        console.log("Backend not ready, retrying in 2 seconds...");
        setTimeout(checkAuth, 2000);
        return;
      }

      const data = await response.json();
      console.log("[checkAuth] /api/auth/me response:", data);
      if (data.version) setVersion(data.version);
      if (data.run_mode) setRunMode(data.run_mode);

      // Check auth mode flags
      if (data.ibm_auth_mode) {
        setIsIbmAuthMode(true);
        setIsNoAuthMode(false);
        setUser(data.authenticated && data.user ? data.user : null);
        console.log(
          "[checkAuth] IBM auth mode — authenticated:",
          data.authenticated,
          "user:",
          data.user,
        );
      } else if (data.no_auth_mode) {
        setIsNoAuthMode(true);
        setIsIbmAuthMode(false);
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
      console.log("[checkAuth] done — isLoading: false");
    } catch (error) {
      console.error("Auth check failed:", error);
      // Network error - backend not ready, keep loading and retry
      console.log("Backend not ready, retrying in 2 seconds...");
      setTimeout(checkAuth, 2000);
    }
  }, []);

  const login = () => {
    // Don't allow login in no-auth mode or IBM auth mode
    if (isNoAuthMode) {
      console.log("Login attempted in no-auth mode - ignored");
      return;
    }
    if (isIbmAuthMode) {
      console.log(
        "Login attempted in IBM auth mode - ignored (auth managed by IBM Watsonx Data)",
      );
      return;
    }

    // Use the correct auth callback URL, not connectors callback
    const redirectUri = `${window.location.origin}/auth/callback`;

    console.log("Starting login with redirect URI:", redirectUri);

    fetch("/api/auth/init", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        connector_type: "google_drive",
        purpose: "app_auth",
        name: "App Authentication",
        redirect_uri: redirectUri,
      }),
    })
      .then((response) => response.json())
      .then((result) => {
        console.log("Auth init response:", result);

        if (result.oauth_config) {
          // Store that this is for app authentication
          localStorage.setItem("auth_purpose", "app_auth");
          localStorage.setItem("connecting_connector_id", result.connection_id);
          localStorage.setItem("connecting_connector_type", "app_auth");
          localStorage.setItem("auth_redirect_to", window.location.pathname);

          console.log("Stored localStorage items:", {
            auth_purpose: localStorage.getItem("auth_purpose"),
            connecting_connector_id: localStorage.getItem(
              "connecting_connector_id",
            ),
            connecting_connector_type: localStorage.getItem(
              "connecting_connector_type",
            ),
          });

          const state = isIbmAuthMode
            ? encodeBase64(
                `id=${result.connection_id}&return=${window.location.origin}/auth/callback`,
              )
            : result.connection_id;

          console.log("OAuth state (encoded):", state);

          const authUrl =
            `${result.oauth_config.authorization_endpoint}?` +
            `client_id=${result.oauth_config.client_id}&` +
            `response_type=code&` +
            `scope=${result.oauth_config.scopes.join(" ")}&` +
            `redirect_uri=${encodeURIComponent(result.oauth_config.redirect_uri)}&` +
            `access_type=offline&` +
            `prompt=consent&` +
            `state=${encodeURIComponent(state)}`;

          console.log("Redirecting to OAuth URL:", authUrl);
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
    console.log("[loginWithIbm] posting to /api/auth/ibm/login");
    const response = await fetch("/api/auth/ibm/login", {
      method: "POST",
      headers: {
        Authorization: "Basic " + btoa(username + ":" + password),
      },
    });
    console.log(
      "[loginWithIbm] response status:",
      response.status,
      "ok:",
      response.ok,
    );
    console.log(
      "[loginWithIbm] response cookies after login:",
      document.cookie,
    );
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "Login failed");
    }
    await checkAuth();
  };

  const logout = async () => {
    if (isNoAuthMode) {
      return;
    }

    try {
      await fetch("/api/auth/logout", {
        method: "POST",
      });
      setUser(null);
    } catch (error) {
      console.error("Logout failed:", error);
    }
  };

  const refreshAuth = async () => {
    await checkAuth();
  };

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
      const r = await fetch("/api/users/me");
      if (!r.ok) {
        resetPermissionState();
        return;
      }
      const data = await r.json();
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
      const r = await fetch("/api/onboarding-status");
      if (!r.ok) return;
      const data = await r.json();
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
