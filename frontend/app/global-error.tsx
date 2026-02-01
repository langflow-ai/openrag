"use client";

import { isChunkLoadError } from "@/lib/utils";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const isChunkError = isChunkLoadError(error);

  return (
    <html lang="en">
      <body>
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "#000",
            color: "#fff",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: "1rem",
              textAlign: "center",
              maxWidth: "28rem",
              padding: "1rem",
            }}
          >
            <h2 style={{ fontSize: "1.25rem", fontWeight: 600, margin: 0 }}>
              {isChunkError ? "Application loading error" : "Component rendering error"}
            </h2>
            <p style={{ color: "#888", margin: 0 }}>
              {isChunkError ? (
                <>
                  Some application resources failed to load.
                  This can occur due to a bad / slow Internet connection,
                  the application server not being fully initialized,
                  or the browser cache containing old code chunk references.
                </>
              ) : (
                "An unexpected component error occurred. See JavaScript Console for further details."
              )}
            </p>
            {error.digest && (
              <p style={{ color: "#666", fontSize: "0.75rem", margin: 0 }}>
                Error ID: {error.digest}
              </p>
            )}
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: "0.5rem 1rem",
                backgroundColor: "#fff",
                color: "#000",
                border: "none",
                borderRadius: "0.375rem",
                cursor: "pointer",
                fontWeight: 500,
              }}
            >
              Reload Page
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
