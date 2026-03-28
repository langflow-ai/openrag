/**
 * Derives the Langflow base URL from the current OpenRAG URL in IBM SaaS environments.
 *
 * IBM SaaS URL pattern:
 *   OpenRAG:  https://{instance_id}.or.{domain}/
 *   Langflow: https://{instance_id}.lf.or.{domain}/
 *
 * The transformation inserts "lf." before the "or." app segment in the hostname.
 * Returns null if the current URL does not match the expected IBM SaaS pattern.
 */
export function deriveCloudLangflowUrl(
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
    url.hostname = `${instanceId}.lf.${orAndDomain}`;
    return url.origin;
  } catch {
    return null;
  }
}
