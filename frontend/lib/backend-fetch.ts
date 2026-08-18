/**
 * Shared helpers for server-side requests to the OpenRAG backend.
 *
 * URL resolution (in priority order):
 *   1. OPENRAG_BACKEND_URL       — full URL, used verbatim (supports https://)
 *   2. OPENRAG_BACKEND_HOST + OPENRAG_BACKEND_PORT + OPENRAG_BACKEND_SSL
 *      (legacy three-var form; preserved so existing deployments need no changes)
 *
 * Custom CA certificate (OPENRAG_BACKEND_CA_CERT_PATH):
 *   When set, every server-side fetch to the backend uses an undici Agent
 *   configured with the supplied CA bundle so Node.js trusts a self-signed or
 *   private-CA-signed backend TLS certificate.  Without this env var the
 *   dispatcher is left undefined (Node's default TLS verification applies).
 *
 * Usage:
 *   import { getBackendBaseUrl, backendFetchInit } from "@/lib/backend-fetch";
 *   const res = await fetch(`${getBackendBaseUrl()}/${path}`, {
 *     ...backendFetchInit(),
 *     headers: { ... },
 *   });
 */

import { readFileSync } from "node:fs";

// Lazily populated so the module can be imported at build time (when env vars
// may not be present) without throwing.
let _agentInit: Record<string, unknown> | undefined;
let _agentInitialised = false;

function buildAgentInit(): Record<string, unknown> | undefined {
  const caPath = process.env.OPENRAG_BACKEND_CA_CERT_PATH;
  if (!caPath) return undefined;

  try {
    // Try to load undici — it is built-in on Node 22+ (via "node:undici") and a
    // production dependency on Node 20.  If neither is available we log a hint
    // and fall back to the default dispatcher (no custom CA).
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    let AgentClass: (typeof import("undici"))["Agent"] | undefined;
    for (const id of ["node:undici", "undici"]) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        AgentClass = (require(id) as typeof import("undici")).Agent;
        break;
      } catch {
        // try next candidate
      }
    }
    if (!AgentClass) {
      console.warn(
        "[backend-fetch] OPENRAG_BACKEND_CA_CERT_PATH is set but undici is not available. " +
          "Custom CA certificate will not be applied. " +
          "Alternative: set NODE_EXTRA_CA_CERTS to the same path.",
      );
      return undefined;
    }
    const ca = readFileSync(caPath);
    const agent = new AgentClass({ connect: { ca } });
    return { dispatcher: agent };
  } catch (err) {
    // Log once and fall back — better than crashing if the file is temporarily missing.
    console.error(
      "[backend-fetch] Failed to build custom CA agent from OPENRAG_BACKEND_CA_CERT_PATH; " +
        "falling back to default TLS verification.",
      err,
    );
    return undefined;
  }
}

/**
 * Returns extra `RequestInit` properties that should be spread into every
 * server-side `fetch` call to the backend.  Currently adds only the custom CA
 * `dispatcher`; returns an empty object when no CA cert is configured.
 */
export function backendFetchInit(): Record<string, unknown> {
  if (!_agentInitialised) {
    _agentInit = buildAgentInit();
    _agentInitialised = true;
  }
  return _agentInit ?? {};
}

/**
 * Returns the backend base URL (no trailing slash).
 * Prefers OPENRAG_BACKEND_URL; falls back to the legacy host+port+SSL form.
 */
export function getBackendBaseUrl(): string {
  const explicit = process.env.OPENRAG_BACKEND_URL;
  if (explicit) return explicit.replace(/\/$/, "");

  const host = process.env.OPENRAG_BACKEND_HOST || "localhost";
  const port = process.env.OPENRAG_BACKEND_PORT || "8000";
  const ssl = process.env.OPENRAG_BACKEND_SSL === "true";
  const scheme = ssl ? "https" : "http";
  return `${scheme}://${host}:${port}`;
}
