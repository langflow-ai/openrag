"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle, Loader2, XCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
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
import { decodeBase64 } from "@/lib/utils";

// remove from localStorage any keys related to the OAuth flow
function cleanupOAuthStorage() {
  localStorage.removeItem("connecting_connector_id");
  localStorage.removeItem("connecting_connector_type");
  localStorage.removeItem("auth_purpose");
  localStorage.removeItem("auth_redirect_to");
}

function AuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { refreshAuth, isIbmAuthMode } = useAuth();
  const redirectTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [purpose] = useState(() => {
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
  const finalConnectorId =
    localStorage.getItem("connecting_connector_id") || state;
  const storedConnectorType = localStorage.getItem("connecting_connector_type");

  const validationError = errorParam
    ? `OAuth error: ${errorParam}`
    : !code || !state || !finalConnectorId
      ? "Missing required parameters for OAuth callback"
      : null;

  const { mutate: exchangeCode, ...callbackMutation } = useMutation({
    mutationFn: async (params: {
      connectionId: string;
      code: string;
      state: string;
    }) => {
      const response = await fetch("/api/auth/callback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connection_id: params.connectionId,
          authorization_code: params.code,
          state: params.state,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "Authentication failed");
      }
      return result as { purpose?: string };
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["connectors"], exact: false });
    },
  });

  useEffect(() => {
    if (validationError) {
      cleanupOAuthStorage();
      return;
    }

    const callbackKey = `callback_processed_${code}`;

    if (sessionStorage.getItem(callbackKey)) return;
    sessionStorage.setItem(callbackKey, "true");

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

    exchangeCode(
      { connectionId: parsedConnectionId, code: code!, state: state! },
      {
        onSuccess: async (result) => {
          if (result.purpose === "app_auth" || purpose === "app_auth") {
            await refreshAuth();

            const redirectTo =
              localStorage.getItem("auth_redirect_to") ||
              searchParams.get("redirect") ||
              "/chat";

            cleanupOAuthStorage();
            redirectTimeoutRef.current = setTimeout(
              () => router.push(redirectTo),
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
        onError: () => {
          cleanupOAuthStorage();
          localStorage.removeItem("test_connection_return_tab");
          sessionStorage.removeItem(callbackKey);
        },
      },
    );

    return () => clearTimeout(redirectTimeoutRef.current);
  }, [
    code,
    state,
    finalConnectorId,
    storedConnectorType,
    validationError,
    searchParams,
    isIbmAuthMode,
    exchangeCode,
    refreshAuth,
    purpose,
    router,
  ]);

  const status: "processing" | "success" | "error" =
    validationError || callbackMutation.isError
      ? "error"
      : callbackMutation.isSuccess
        ? "success"
        : "processing";

  const error =
    validationError ||
    (callbackMutation.error instanceof Error
      ? callbackMutation.error.message
      : null);

  const isAppAuth = purpose === "app_auth";
  const isTest = purpose === "test";

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
