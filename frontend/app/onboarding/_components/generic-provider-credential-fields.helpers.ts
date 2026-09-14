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
