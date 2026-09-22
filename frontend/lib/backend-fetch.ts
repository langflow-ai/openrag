/**
 * Shared helpers for server-side requests to the OpenRAG backend.
 *
 * URL resolution (in priority order):
 *   1. OPENRAG_BACKEND_URL       — full URL, used verbatim (supports https://)
 *   2. OPENRAG_BACKEND_HOST + OPENRAG_BACKEND_PORT + OPENRAG_BACKEND_SSL
 *      (legacy three-var form; preserved so existing deployments need no changes)
 *
 * Custom CA certificate (OPENRAG_BACKEND_CA_CERT_PATH):
 *   When set, every server-side fetch to the backend uses undici's own fetch
 *   function (not globalThis.fetch) with an Agent configured with the supplied
 *   CA bundle.  This is required because globalThis.fetch in Node 18+ is the
 *   built-in Web Fetch API and silently ignores the `dispatcher` option, so
 *   NODE_EXTRA_CA_CERTS and passing `dispatcher` to globalThis.fetch both have
 *   no effect on undici's TLS stack.  Calling undici.fetch directly is the only
 *   reliable way to inject a custom CA into server-side requests.
 *
 *   Without OPENRAG_BACKEND_CA_CERT_PATH the module falls back to
 *   globalThis.fetch (Node's default TLS verification applies).
 *
 * Usage:
 *   import { getBackendBaseUrl, backendFetch } from "@/lib/backend-fetch";
 *   const res = await backendFetch(`${getBackendBaseUrl()}/${path}`, {
 *     method: "POST",
 *     headers: { ... },
 *     body: "...",
 *   });
 */

import { readFileSync } from "node:fs";

// ---------------------------------------------------------------------------
// Internal state — lazily initialised on first call so this module is safe to
// import at build time when env vars may not yet be present.
// ---------------------------------------------------------------------------

type UndiciFetch = typeof import("undici")["fetch"];
type UndiciRequestInit = Parameters<UndiciFetch>[1];
type UndiciDispatcher = import("undici").Dispatcher;

let _initialised = false;
// When a custom CA is configured: the bound undici.fetch with the agent baked
// in via the dispatcher option.  When not configured: undefined (caller falls
// back to globalThis.fetch).
let _customFetch: UndiciFetch | undefined;

function initialise(): void {
  if (_initialised) return;
  _initialised = true;

  const caPath = process.env.OPENRAG_BACKEND_CA_CERT_PATH;
  if (!caPath) return;

  try {
    // undici is a direct production dependency (see package.json).  We also
    // try the built-in "node:undici" alias available on Node 22+.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    let undiciModule: typeof import("undici") | undefined;
    for (const id of ["node:undici", "undici"]) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        undiciModule = require(id) as typeof import("undici");
        break;
      } catch {
        // try next candidate
      }
    }

    if (!undiciModule) {
      console.warn(
        "[backend-fetch] OPENRAG_BACKEND_CA_CERT_PATH is set but undici is not " +
          "available. Custom CA certificate will not be applied.",
      );
      return;
    }

    const ca = readFileSync(caPath);
    const agent: UndiciDispatcher = new undiciModule.Agent({ connect: { ca } });

    // Bind undici's own fetch with the custom dispatcher so every call through
    // backendFetch() uses this agent.  globalThis.fetch ignores `dispatcher`
    // because it is the Web Fetch API, not undici.fetch — this is the fix.
    const undicicFetch = undiciModule.fetch;
    _customFetch = (input, init) =>
      undicicFetch(input, { ...(init as UndiciRequestInit), dispatcher: agent });

    console.info(
      "[backend-fetch] Custom CA loaded from OPENRAG_BACKEND_CA_CERT_PATH; " +
        "using undici.fetch with custom dispatcher for backend requests.",
    );
  } catch (err) {
    console.error(
      "[backend-fetch] Failed to build custom CA agent from OPENRAG_BACKEND_CA_CERT_PATH; " +
        "falling back to default TLS verification.",
      err,
    );
  }
}

/**
 * Drop-in replacement for `fetch` for all server-side requests to the backend.
 *
 * When OPENRAG_BACKEND_CA_CERT_PATH is set this calls undici's own `fetch`
 * with a custom CA Agent as the dispatcher.  Otherwise it falls through to
 * globalThis.fetch so behaviour is identical to before for plain HTTP or
 * publicly-trusted HTTPS backends.
 */
export function backendFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  if (!_initialised) initialise();
  if (_customFetch) {
    // undici.fetch accepts the same (input, init) signature as globalThis.fetch.
    // Cast through unknown because undici's Response type diverges slightly from
    // the global Response in typings only — the runtime objects are compatible.
    return _customFetch(
      input as Parameters<UndiciFetch>[0],
      init as UndiciRequestInit,
    ) as unknown as Promise<Response>;
  }
  return fetch(input, init);
}

/**
 * @deprecated Use `backendFetch(url, init)` directly.  This shim is kept for
 * any call sites that still spread `backendFetchInit()` into a globalThis.fetch
 * call — those calls will NOT apply the custom CA because globalThis.fetch
 * silently ignores the `dispatcher` option.  Migrate to `backendFetch`.
 */
export function backendFetchInit(): Record<string, unknown> {
  // Return an empty object.  The dispatcher is now handled inside backendFetch.
  return {};
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
