"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from "react";

interface User {
  user_id: string;
  email: string;
  name: string;
  picture?: string;
  provider: string;
  last_login?: string;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isNoAuthMode: boolean;
  login: () => void;
  logout: () => Promise<void>;
  refreshAuth: () => Promise<void>;
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

  const checkAuth = useCallback(async () => {
    try {
      const response = await fetch("/api/auth/me");

      // If we can't reach the backend, keep loading
      if (!response.ok && (response.status === 0 || response.status >= 500)) {
        console.log("Backend not ready, retrying in 2 seconds...");
        setTimeout(checkAuth, 2000);
        return;
      }

      const data = await response.json();

      // Check if we're in no-auth mode
      if (data.no_auth_mode) {
        setIsNoAuthMode(true);
        setUser(null);
      } else if (data.authenticated && data.user) {
        setIsNoAuthMode(false);
        setUser(data.user);
      } else {
        setIsNoAuthMode(false);
        setUser(null);
      }

      setIsLoading(false);
    } catch (error) {
      console.error("Auth check failed:", error);
      // Network error - backend not ready, keep loading and retry
      console.log("Backend not ready, retrying in 2 seconds...");
      setTimeout(checkAuth, 2000);
    }
  }, []);

  const login = () => {
    // Don't allow login in no-auth mode
    if (isNoAuthMode) {
      console.log("Login attempted in no-auth mode - ignored");
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

          console.log("Stored localStorage items:", {
            auth_purpose: localStorage.getItem("auth_purpose"),
            connecting_connector_id: localStorage.getItem(
              "connecting_connector_id",
            ),
            connecting_connector_type: localStorage.getItem(
              "connecting_connector_type",
            ),
          });

          const authUrl =
            `${result.oauth_config.authorization_endpoint}?` +
            `client_id=${result.oauth_config.client_id}&` +
            `response_type=code&` +
            `scope=${result.oauth_config.scopes.join(" ")}&` +
            `redirect_uri=${encodeURIComponent(result.oauth_config.redirect_uri)}&` +
            `access_type=offline&` +
            `prompt=consent&` +
            `state=${result.connection_id}`;

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

  const logout = async () => {
    // Don't allow logout in no-auth mode
    if (isNoAuthMode) {
      console.log("Logout attempted in no-auth mode - ignored");
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

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user,
    isNoAuthMode,
    login,
    logout,
    refreshAuth,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
