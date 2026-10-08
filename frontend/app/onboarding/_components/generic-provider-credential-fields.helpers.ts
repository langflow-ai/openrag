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
  if (provider === "azure") {
    return new Set([
      "api_base",
      "api_version",
      ...(AZURE_AUTH_GROUPS.find((group) => group.key === azureAuthMethod)
        ?.fields ?? []),
    ]);
  }
  if (provider === "watsonx_onprem") {
    return new Set([
      ...ON_PREM_SHARED_FIELDS,
      ...(onPremAuthMethod === "zen_api_key"
        ? ["zen_api_key"]
        : ["username", "api_key"]),
    ]);
  }
  return null;
}
