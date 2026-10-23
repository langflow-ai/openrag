/**
 * The catalogue `field_type` of a provider's `ssl_verify` credential, rendered
 * by `TlsVerificationField`. Mirrors `KNOWN_FIELD_TYPES` in `model_catalog.py`.
 */
export const TLS_VERIFY_FIELD_TYPE = "tls_verify";

/**
 * Values of a provider's `ssl_verify` credential that mean "do not verify".
 * Mirrors `_FALSE_VALUES` / `_FALSE_TLS_VALUES` in the RHOAI and watsonx.ai
 * on-prem enhancement modules.
 */
const TLS_DISABLED_VALUES: Record<string, true> = {
  false: true,
  "0": true,
  no: true,
  off: true,
};

/** Values that mean "verify against the default trust store". */
const TLS_ENABLED_VALUES: Record<string, true> = {
  true: true,
  "1": true,
  yes: true,
  on: true,
};

/**
 * Whether a stored `ssl_verify` turns verification off. Anything unrecognised
 * is a CA bundle path, so verification stays on — the backend fails closed the
 * same way.
 */
export function isTlsVerificationDisabled(value?: string | null): boolean {
  return TLS_DISABLED_VALUES[(value ?? "").trim().toLowerCase()] === true;
}

/**
 * Whether a stored `ssl_verify` is the default: blank, or a true-equivalent
 * word. Neither names a CA bundle nor turns verification off.
 */
export function isDefaultTlsSetting(value?: string | null): boolean {
  const normalized = (value ?? "").trim().toLowerCase();
  return !normalized || TLS_ENABLED_VALUES[normalized] === true;
}

/** A stored `ssl_verify` as the toggle and the CA path box show it. */
export function parseTlsSetting(value?: string | null): {
  enabled: boolean;
  caPath: string;
} {
  if (isTlsVerificationDisabled(value)) return { enabled: false, caPath: "" };
  if (isDefaultTlsSetting(value)) return { enabled: true, caPath: "" };
  return { enabled: true, caPath: value ?? "" };
}
