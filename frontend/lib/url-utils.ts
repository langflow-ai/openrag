export interface LangflowEditUrlParams {
  /** Flow ID to open directly (e.g. settings.ingest_flow_id). */
  flowId?: string | null;
  /** Explicit override URL that wins over any derived/computed value. */
  editUrlOverride?: string | null;
  /** Operator-configured public Langflow URL (settings.langflow_public_url). */
  publicUrl?: string | null;
  /** Whether the deployment is in IBM auth mode. */
  isIbmAuthMode: boolean;
  /** Backend run mode ("oss" | "saas" | "on_prem"), used to pick the IBM URL derivation. */
  runMode: string | null;
  /** Current origin; defaults to window.location.origin in the browser. */
  locationOrigin?: string;
}

/**
 * Resolves the Langflow editor URL for the current deployment, used by the
 * "Edit in Langflow" actions in the settings sections.
 *
 * Precedence: an explicit `editUrlOverride` always wins. Otherwise a base URL
 * is chosen in order of: IBM-derived URL (SaaS or on-prem, when in IBM auth
 * mode) → operator-configured `publicUrl` → same-host `:7860` → localhost. The
 * `flowId`, when present, is appended as `/flow/{flowId}`.
 */
export function resolveLangflowEditUrl({
  flowId,
  editUrlOverride,
  publicUrl,
  isIbmAuthMode,
  runMode,
  locationOrigin = typeof window !== "undefined" ? window.location.origin : "",
}: LangflowEditUrlParams): string {
  const ibmLangflowUrl =
    isIbmAuthMode && locationOrigin
      ? runMode === "on_prem"
        ? deriveOnPremLangflowUrl(locationOrigin)
        : deriveCloudLangflowUrl(locationOrigin)
      : null;

  let derivedFromOrigin = "";
  if (locationOrigin) {
    try {
      const url = new URL(locationOrigin);
      derivedFromOrigin = `${url.protocol}//${url.hostname}:7860`;
    } catch {
      derivedFromOrigin = "";
    }
  }

  const base = (
    ibmLangflowUrl ||
    publicUrl ||
    derivedFromOrigin ||
    "http://localhost:7860"
  ).replace(/\/$/, "");
  const computed = flowId ? `${base}/flow/${flowId}` : base;
  return editUrlOverride || computed;
}

/**
 * Derives the Langflow base URL from the current OpenRAG URL in IBM SaaS environments.
 *
 * IBM SaaS URL pattern:
 *   OpenRAG:  https://{instance_id}.or.{domain}/
 *   Langflow: https://{instance_id}-langflow.or.{domain}/
 *
 * The transformation appends "-langflow" to the instance ID segment of the hostname.
 * Returns null if the current URL does not match the expected IBM SaaS pattern.
 */
function deriveCloudLangflowUrl(
  locationOrigin: string = typeof window !== "undefined"
    ? window.location.origin
    : "",
): string | null {
  if (!locationOrigin) return null;

  try {
    const url = new URL(locationOrigin);
    // Match: {instance_id}.or.{rest-of-domain}
    // We look for a hostname segment "or" that is preceded by an instance ID and followed by more domain parts.
    const hostname = url.hostname;
    const match = hostname.match(/^([^.]+)\.(or\..+)$/);
    if (!match) return null;

    const [, instanceId, orAndDomain] = match;
    url.hostname = `${instanceId}-langflow.${orAndDomain}`;
    return url.origin;
  } catch {
    return null;
  }
}

/**
 * Derives the Langflow base URL from the current OpenRAG URL in IBM on-prem (CPD) environments.
 *
 * IBM on-prem URL pattern:
 *   https://openrag-{app}-{instance_namespace}.{ingress_name}
 *   where {app} is "fe" (frontend) or "lf" (Langflow).
 *
 * Examples:
 *   OpenRAG:  https://openrag-fe-cpd-instance.apps.sythis.cp.fyre.ibm.com/
 *   Langflow: https://openrag-lf-cpd-instance.apps.sythis.cp.fyre.ibm.com/
 *
 * The transformation swaps the "openrag-fe-" host prefix for "openrag-lf-".
 * Returns null if the current URL does not match the expected on-prem pattern.
 */
function deriveOnPremLangflowUrl(
  locationOrigin: string = typeof window !== "undefined"
    ? window.location.origin
    : "",
): string | null {
  if (!locationOrigin) return null;

  try {
    const url = new URL(locationOrigin);
    // Match: openrag-fe-{instance_namespace}.{ingress_name}
    const hostname = url.hostname;
    const match = hostname.match(/^openrag-fe-(.+)$/);
    if (!match) return null;

    const [, instanceAndIngress] = match;
    url.hostname = `openrag-lf-${instanceAndIngress}`;
    return url.origin;
  } catch {
    return null;
  }
}
