"use client";

import { ArrowLeft, CheckCircle, Loader2, XCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
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

function AuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refreshAuth, isIbmAuthMode } = useAuth();
  const [status, setStatus] = useState<"processing" | "success" | "error">(
    "processing",
  );
  const [error, setError] = useState<string | null>(null);
  const [purpose, setPurpose] = useState<string>("app_auth");
  const [redirectTarget, setRedirectTarget] = useState<string | null>(null);

  // Handle the OAuth callback exchange
  useEffect(() => {
    const code = searchParams.get("code");
    const callbackKey = `callback_processed_${code}`;

    if (sessionStorage.getItem(callbackKey)) {
      return;
    }
    sessionStorage.setItem(callbackKey, "true");

    const handleCallback = async () => {
      try {
        const state = searchParams.get("state");
        const errorParam = searchParams.get("error");

        console.log("OAuth callback state (raw):", state);

        const connectorId = localStorage.getItem("connecting_connector_id");
        const storedConnectorType = localStorage.getItem(
          "connecting_connector_type",
        );
        const authPurpose = localStorage.getItem("auth_purpose");

        const detectedPurpose =
          authPurpose ||
          (storedConnectorType && storedConnectorType !== "app_auth"
            ? "data_source"
            : "app_auth");
        setPurpose(detectedPurpose);

        console.log("OAuth Callback Debug:", {
          urlParams: { code: !!code, state: !!state, error: errorParam },
          localStorage: { connectorId, storedConnectorType, authPurpose },
          detectedPurpose,
          fullUrl: window.location.href,
        });

        const finalConnectorId = connectorId || state;

        if (errorParam) {
          throw new Error(`OAuth error: ${errorParam}`);
        }

        if (!code || !state || !finalConnectorId) {
          console.error("Missing OAuth callback parameters:", {
            code: !!code,
            state: !!state,
            finalConnectorId: !!finalConnectorId,
          });
          throw new Error("Missing required parameters for OAuth callback");
        }

        const stateParam = searchParams.get("state");
        let parsedConnectionId = finalConnectorId;

        if (isIbmAuthMode && stateParam) {
          try {
            const decodedState = decodeBase64(stateParam);
            console.log("OAuth callback state (decoded):", decodedState);
            const params = new URLSearchParams(decodedState);

            if (params.has("id")) {
              parsedConnectionId = params.get("id") || finalConnectorId;
              console.log("Parsed Base64 state parameter:", {
                parsedConnectionId,
                stateReturnUrl: params.get("return"),
              });
            } else if (stateParam.includes("id=")) {
              const rawParams = new URLSearchParams(stateParam);
              parsedConnectionId = rawParams.get("id") || finalConnectorId;
            }
          } catch (e) {
            console.error(
              "Failed to Base64 decode or parse state parameter",
              e,
            );
            if (stateParam.includes("id=")) {
              try {
                const params = new URLSearchParams(stateParam);
                parsedConnectionId = params.get("id") || finalConnectorId;
              } catch (innerE) {
                console.error("Failed to parse raw state parameter", innerE);
              }
            }
          }
        }

        const response = await fetch("/api/auth/callback", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            connection_id: parsedConnectionId,
            authorization_code: code,
            state: state,
          }),
        });

        const result = await response.json();

        if (response.ok) {
          if (result.purpose === "app_auth" || detectedPurpose === "app_auth") {
            await refreshAuth();

            const redirectTo =
              localStorage.getItem("auth_redirect_to") ||
              searchParams.get("redirect") ||
              "/chat";

            localStorage.removeItem("connecting_connector_id");
            localStorage.removeItem("connecting_connector_type");
            localStorage.removeItem("auth_purpose");
            localStorage.removeItem("auth_redirect_to");

            setRedirectTarget(redirectTo);
          } else {
            localStorage.removeItem("connecting_connector_id");
            localStorage.removeItem("connecting_connector_type");
            localStorage.removeItem("auth_purpose");

            setRedirectTarget("/settings?oauth_success=true");
          }
          setStatus("success");
        } else {
          throw new Error(result.error || "Authentication failed");
        }
      } catch (err) {
        console.error("OAuth callback error:", err);
        setError(err instanceof Error ? err.message : "Unknown error occurred");
        setStatus("error");

        localStorage.removeItem("connecting_connector_id");
        localStorage.removeItem("connecting_connector_type");
        localStorage.removeItem("auth_purpose");
        localStorage.removeItem("auth_redirect_to");
      }
    };

    handleCallback();
  }, [searchParams, refreshAuth, isIbmAuthMode]);

  // Redirect after successful callback — separate effect so it works
  // regardless of which mount's async callback set the status.
  useEffect(() => {
    if (status === "success" && redirectTarget) {
      const timeoutId = setTimeout(() => {
        router.push(redirectTarget);
      }, 2000);
      return () => clearTimeout(timeoutId);
    }
  }, [status, redirectTarget, router]);

  // Dynamic UI content based on purpose
  const isAppAuth = purpose === "app_auth";

  const getTitle = () => {
    if (status === "processing") {
      return isAppAuth ? "Signing you in..." : "Connecting...";
    }
    if (status === "success") {
      return isAppAuth ? "Welcome to OpenRAG!" : "Connection Successful!";
    }
    if (status === "error") {
      return isAppAuth ? "Sign In Failed" : "Connection Failed";
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
                onClick={() => router.push(isAppAuth ? "/login" : "/settings")}
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
