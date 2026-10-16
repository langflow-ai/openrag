import type { CatalogCredentialField } from "@/components/models/catalog-models";

export const AZURE_AUTH_GROUPS = [
  { key: "api_key", label: "API key", fields: ["api_key"] },
  {
    key: "entra_token",
    label: "Microsoft Entra access token",
    fields: ["azure_ad_token"],
  },
  {
    key: "service_principal",
    label: "Microsoft Entra service principal",
    fields: ["tenant_id", "client_id", "client_secret"],
  },
] as const;

export const ON_PREM_AUTH_GROUPS = [
  {
    key: "username_api_key",
    label: "Username + API key",
    fields: ["username", "api_key"],
  },
  { key: "zen_api_key", label: "Zen API key", fields: ["zen_api_key"] },
] as const;

export function fieldsForKeys(
  fields: CatalogCredentialField[],
  keys: readonly string[],
) {
  const byKey = new Map(fields.map((field) => [field.key, field]));
  return keys.flatMap((key) => {
    const field = byKey.get(key);
    return field ? [field] : [];
  });
}

const ON_PREM_SHARED_FIELDS = [
  "api_base",
  "space_id",
  "project_id",
  "ssl_verify",
];

/**
 * The keys of the chosen auth method itself — every one of them, since a
 * method authenticates only once all of its fields are filled. A catalogue
 * field's `required` flag cannot say this: `username` is needed for the
 * username + API key method and meaningless for a Zen API key. Shared fields
 * (endpoint, TLS) are not included; they keep their own `required` flag.
 *
 * Empty when the provider has no auth-method choice.
 */
export function authMethodCredentialKeys(
  provider: string,
  azureAuthMethod: string,
  onPremAuthMethod: string,
): readonly string[] {
  if (provider === "azure") {
    return (
      AZURE_AUTH_GROUPS.find((group) => group.key === azureAuthMethod)
        ?.fields ?? []
    );
  }
  if (provider === "watsonx_onprem") {
    // Anything but a Zen API key is the username + API key pair, the method
    // the form offers first.
    return (
      ON_PREM_AUTH_GROUPS.find((group) => group.key === onPremAuthMethod) ??
      ON_PREM_AUTH_GROUPS[0]
    ).fields;
  }
  return [];
}

/**
 * The credential keys the chosen auth method actually uses, or `null` when the
 * provider has no auth-method choice and every field applies.
 *
 * Values typed for the *other* method stay in the form so switching back
 * keeps them, but they must not be submitted — nor sent to a cluster when
 * onboarding asks it which models it serves.
 */
export function activeCredentialKeys(
  provider: string,
  azureAuthMethod: string,
  onPremAuthMethod: string,
): Set<string> | null {
  const methodKeys = authMethodCredentialKeys(
    provider,
    azureAuthMethod,
    onPremAuthMethod,
  );
  if (provider === "azure") {
    return new Set(["api_base", "api_version", ...methodKeys]);
  }
  if (provider === "watsonx_onprem") {
    return new Set([...ON_PREM_SHARED_FIELDS, ...methodKeys]);
  }
  return null;
}

/**
 * Fields that say *where* credentials are sent. Mirrors
 * `CREDENTIAL_TARGET_FIELDS` in `src/config/config_manager.py`: once a form
 * changes one — or clears one that was saved — the backend refuses to reuse a
 * stored secret, for model discovery and for Submit alike. Onboarding and the
 * Settings provider dialog both apply this rule.
 */
export const CREDENTIAL_TARGET_FIELDS = [
  "api_base",
  "embedding_api_base",
  "ssl_verify",
] as const;

/** Shown under a saved secret that must be typed again after a target change. */
export const SECRET_REENTRY_HINT =
  "The endpoint or TLS setting changed, so the saved value is not sent to it. Enter it again.";

/** Whether the form points the credentials somewhere other than the saved target. */
export function credentialTargetChanged(
  credentials: Record<string, string>,
  savedCredentials: Record<string, string>,
): boolean {
  return CREDENTIAL_TARGET_FIELDS.some(
    (key) =>
      (credentials[key] ?? "").trim() !== (savedCredentials[key] ?? "").trim(),
  );
}

/**
 * Saved secrets the operator has to type again before Submit.
 *
 * A blank secret normally means "keep the saved one", but the backend refuses
 * that once the target changed (it would send the token to a host it was not
 * saved for). Only secrets the chosen auth method uses count: the backend
 * drops the other method's values on save anyway.
 */
export function secretsToReenter(
  credentials: Record<string, string>,
  savedSecrets: Set<string>,
  active: Set<string> | null,
  targetChanged: boolean,
): string[] {
  if (!targetChanged) return [];
  return [...savedSecrets].filter(
    (key) =>
      (!active || active.has(key)) && (credentials[key] ?? "").trim() === "",
  );
}

/**
 * The keys the operator emptied that still hold a saved non-secret value.
 *
 * A secret is never shown, so a blank one means "keep the saved value". Any
 * other field is shown pre-filled, so blanking it means "clear it": Submit
 * sends these as removals, and model discovery sends them as `""` so the
 * cluster is not asked at the endpoint the operator just removed.
 */
export function clearedSavedCredentialKeys(
  credentials: Record<string, string>,
  savedCredentials: Record<string, string>,
  savedSecrets: Set<string>,
  active: Set<string> | null,
): string[] {
  return Object.entries(credentials)
    .filter(
      ([key, value]) =>
        (!active || active.has(key)) &&
        (value ?? "").trim() === "" &&
        !savedSecrets.has(key) &&
        Boolean(savedCredentials[key]),
    )
    .map(([key]) => key);
}
