"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle, Loader2, XCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Suspense,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import AnimatedProcessingIcon from "@/components/icons/animated-processing-icon";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/contexts/auth-context";
import { apiClient } from "@/lib/api-client";
import { decodeBase64 } from "@/lib/utils";

// remove from localStorage any keys related to the OAuth flow
function cleanupOAuthStorage() {
  localStorage.removeItem("connecting_connector_id");
  localStorage.removeItem("connecting_connector_type");
  localStorage.removeItem("auth_purpose");
  localStorage.removeItem("auth_redirect_to");
}

type CallbackResult = { purpose?: string };

// One exchange per single-use code, kept after settling so re-runs and remounts
// reuse it instead of POSTing the spent code again.
const exchanges = new Map<string, Promise<CallbackResult>>();

const callbackKeyFor = (code: string) => `callback_processed_${code}`;

function AuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { refreshAuth, isIbmAuthMode } = useAuth();
  const redirectTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const [purpose] = useState(() => {
    if (typeof window === "undefined") return "app_auth";
    const authPurpose = localStorage.getItem("auth_purpose");
    const storedConnectorType = localStorage.getItem(
      "connecting_connector_type",
    );
    return (
      authPurpose ||
      (storedConnectorType && storedConnectorType !== "app_auth"
        ? "data_source"
        : "app_auth")
    );
  });

  const errorParam = searchParams.get("error");
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const [finalConnectorId] = useState(() =>
    typeof window !== "undefined"
      ? localStorage.getItem("connecting_connector_id") || state
      : state,
  );
  const [storedConnectorType] = useState(() =>
    typeof window !== "undefined"
      ? localStorage.getItem("connecting_connector_type")
      : null,
  );
  // Read once: cleanupOAuthStorage() clears auth_redirect_to.
  const [appAuthRedirectTo] = useState(
    () =>
      (typeof window !== "undefined" &&
        localStorage.getItem("auth_redirect_to")) ||
      searchParams.get("redirect") ||
      "/chat",
  );

  // Reload / back button: an earlier load spent the code and nothing is in flight.
  const [codeAlreadyUsed] = useState(
    () =>
      typeof window !== "undefined" &&
      !!code &&
      !exchanges.has(code) &&
      !!sessionStorage.getItem(callbackKeyFor(code)),
  );

  const validationError = errorParam
    ? `OAuth error: ${errorParam}`
    : !code || !state || !finalConnectorId
      ? "Missing required parameters for OAuth callback"
      : codeAlreadyUsed
        ? "This sign-in link has already been used. Please try again."
        : null;

  const [exchangeResult, setExchangeResult] = useState<
    { status: "success" } | { status: "error"; error: string } | null
  >(null);

  useEffect(() => {
    if (validationError) {
      cleanupOAuthStorage();
      return;
    }

    const callbackKey = callbackKeyFor(code!);
    let active = true;

    let parsedConnectionId = finalConnectorId!;

    if (isIbmAuthMode && state) {
      try {
        const decodedState = decodeBase64(state);
        const params = new URLSearchParams(decodedState);

        if (params.has("id")) {
          parsedConnectionId = params.get("id") || finalConnectorId!;
        } else if (state.includes("id=")) {
          const rawParams = new URLSearchParams(state);
          parsedConnectionId = rawParams.get("id") || finalConnectorId!;
        }
      } catch (e) {
        console.error("Failed to Base64 decode or parse state parameter", e);
        if (state.includes("id=")) {
          try {
            const params = new URLSearchParams(state);
            parsedConnectionId = params.get("id") || finalConnectorId!;
          } catch (innerE) {
            console.error("Failed to parse raw state parameter", innerE);
          }
        }
      }
    }

    let exchange = exchanges.get(code!);
    if (!exchange) {
      sessionStorage.setItem(callbackKey, "true");
      exchange = apiClient
        .post("/auth/callback", {
          connection_id: parsedConnectionId,
          authorization_code: code,
          state,
        })
        .then((response) => {
          const result = response.data;
          if (response.status < 200 || response.status >= 300) {
            throw new Error(result.error || "Authentication failed");
          }
          return result as CallbackResult;
        })
        .finally(() => {
          queryClient.invalidateQueries({
            queryKey: ["connectors"],
            exact: false,
          });
        });
      exchanges.set(code!, exchange);
    }

    exchange.then(
      async (result) => {
        if (!active) return;
        setExchangeResult({ status: "success" });
        if (result.purpose === "app_auth" || purpose === "app_auth") {
          await refreshAuth();
          if (!active) return;

          cleanupOAuthStorage();
          redirectTimeoutRef.current = setTimeout(
            () => router.push(appAuthRedirectTo),
            2000,
          );
        } else if (result.purpose === "test" || purpose === "test") {
          // Test Connection — token exchange succeeded, credentials work. No
          // connection was persisted (see _handle_test_auth); send the admin
          // back to Connector Settings with a success indicator to toast.
          cleanupOAuthStorage();
          localStorage.removeItem("test_connection_return_tab");
          redirectTimeoutRef.current = setTimeout(
            () =>
              router.push(
                `/settings/connector-access?oauth_test=success&credential=${encodeURIComponent(storedConnectorType || "")}`,
              ),
            1000,
          );
        } else {
          cleanupOAuthStorage();
          redirectTimeoutRef.current = setTimeout(
            () => router.push("/settings?oauth_success=true"),
            2000,
          );
        }
      },
      (error: unknown) => {
        if (!active) return;
        setExchangeResult({
          status: "error",
          error:
            error instanceof Error ? error.message : "Authentication failed",
        });
        cleanupOAuthStorage();
        localStorage.removeItem("test_connection_return_tab");
        sessionStorage.removeItem(callbackKey);
      },
    );

    return () => {
      active = false;
      clearTimeout(redirectTimeoutRef.current);
    };
  }, [
    code,
    state,
    finalConnectorId,
    storedConnectorType,
    validationError,
    appAuthRedirectTo,
    isIbmAuthMode,
    queryClient,
    refreshAuth,
    purpose,
    router,
  ]);

  const status: "processing" | "success" | "error" = validationError
    ? "error"
    : (exchangeResult?.status ?? "processing");

  const error =
    validationError ||
    (exchangeResult?.status === "error" ? exchangeResult.error : null);

  const isAppAuth = mounted && purpose === "app_auth";
  const isTest = mounted && purpose === "test";

  const getTitle = () => {
    if (status === "processing") {
      return isAppAuth
        ? "Signing you in..."
        : isTest
          ? "Testing connection..."
          : "Connecting...";
    }
    if (status === "success") {
      return isAppAuth
        ? "Welcome to OpenRAG!"
        : isTest
          ? "Test Successful!"
          : "Connection Successful!";
    }
    if (status === "error") {
      return isAppAuth
        ? "Sign In Failed"
        : isTest
          ? "Test Failed"
          : "Connection Failed";
    }
  };

  const getDescription = () => {
    if (status === "processing") {
      return isAppAuth
        ? "Please wait while we complete your sign in..."
        : "Please wait while we complete the connection...";
    }
    if (status === "success") {
      return "You will be redirected shortly.";
    }
    if (status === "error") {
      return isAppAuth
        ? "There was an issue signing you in."
        : "There was an issue with the connection.";
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-card rounded-lg m-4">
      <Card className="w-full max-w-md bg-card rounded-lg m-4">
        <CardHeader className="text-center">
          <CardTitle className="flex items-center justify-center gap-2">
            {status === "processing" && (
              <>
                <AnimatedProcessingIcon className="h-5 w-5 text-current" />
                {getTitle()}
              </>
            )}
            {status === "success" && (
              <>
                <CheckCircle className="h-5 w-5 text-green-500" />
                {getTitle()}
              </>
            )}
            {status === "error" && (
              <>
                <XCircle className="h-5 w-5 text-red-500" />
                {getTitle()}
              </>
            )}
          </CardTitle>
          <CardDescription>{getDescription()}</CardDescription>
        </CardHeader>
        <CardContent>
          {status === "error" && (
            <div className="space-y-4">
              <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                <p className="text-sm text-red-600">{error}</p>
              </div>
              <Button
                onClick={() =>
                  router.push(
                    isAppAuth
                      ? "/login"
                      : isTest
                        ? "/settings/connector-access"
                        : "/settings",
                  )
                }
                variant="outline"
                className="w-full"
              >
                <ArrowLeft className="h-4 w-4 mr-2" />
                {isAppAuth ? "Back to Login" : "Back to Settings"}
              </Button>
            </div>
          )}
          {status === "success" && (
            <div className="text-center">
              <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                <p className="text-sm text-green-600">
                  {isAppAuth
                    ? "Redirecting you to the app..."
                    : "Redirecting to settings..."}
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-background">
          <Card className="w-full max-w-md">
            <CardHeader className="text-center">
              <CardTitle className="flex items-center justify-center gap-2">
                <Loader2 className="h-5 w-5 animate-spin" />
                Loading...
              </CardTitle>
              <CardDescription>
                Please wait while we process your request...
              </CardDescription>
            </CardHeader>
          </Card>
        </div>
      }
    >
      <AuthCallbackContent />
    </Suspense>
  );
}
