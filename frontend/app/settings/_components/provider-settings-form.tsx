import { useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import type { CatalogCredentialField } from "@/components/models/catalog-models";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export interface ProviderSettingsFormData {
  credentials: Record<string, string>;
}

const AZURE_AUTH_GROUPS = [
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

const ON_PREM_AUTH_GROUPS = [
  {
    key: "username_api_key",
    label: "Username + API key",
    fields: ["username", "api_key"],
  },
  { key: "zen_api_key", label: "Zen API key", fields: ["zen_api_key"] },
] as const;

/**
 * Credential form for a provider with no bespoke dialog, rendered from the
 * field spec `/api/models/catalog` publishes for it. A provider added to
 * `config/model_providers.yaml` is configurable through this without any
 * further frontend work.
 */
export function ProviderSettingsForm({
  provider,
  providerName,
  fields,
  savedSecretFields,
  saveError,
  azureAuthMethod,
  onAzureAuthMethodChange,
  onPremAuthMethod,
  onOnPremAuthMethodChange,
}: {
  provider: string;
  providerName: string;
  fields: CatalogCredentialField[];
  savedSecretFields: string[];
  saveError?: string | null;
  azureAuthMethod?: string;
  onAzureAuthMethodChange?: (method: string) => void;
  onPremAuthMethod?: string;
  onOnPremAuthMethodChange?: (method: string) => void;
}) {
  const {
    register,
    formState: { errors },
  } = useFormContext<ProviderSettingsFormData>();

  const saved = new Set(savedSecretFields);

  const renderField = (field: CatalogCredentialField) => {
    const error = errors.credentials?.[field.key]?.message;
    const isSecret =
      field.field_type === "password" || field.field_type === "textarea";
    const hasSaved = isSecret && saved.has(field.key);
    // A stored secret is never sent back to the browser, so an empty box
    // means "keep what is saved" rather than "no value" — required only
    // bites when nothing is stored yet.
    const required = field.required && !hasSaved;

    return (
      <div key={field.key} className="min-w-0 space-y-2">
        <LabelWrapper
          label={field.label}
          helperText={field.tooltip ?? undefined}
          required={required}
          id={`provider-field-${field.key}`}
        >
          {field.field_type === "textarea" ? (
            <Textarea
              {...register(`credentials.${field.key}`, {
                required: required ? `${field.label} is required` : false,
              })}
              className={error ? "!border-destructive" : ""}
              id={`provider-field-${field.key}`}
              placeholder={
                hasSaved ? "•••••••••" : (field.placeholder ?? undefined)
              }
            />
          ) : (
            <Input
              {...register(`credentials.${field.key}`, {
                required: required ? `${field.label} is required` : false,
              })}
              className={error ? "!border-destructive" : ""}
              id={`provider-field-${field.key}`}
              type={field.field_type === "password" ? "password" : "text"}
              autoComplete={
                field.field_type === "password" ? "new-password" : "off"
              }
              placeholder={
                hasSaved ? "•••••••••" : (field.placeholder ?? undefined)
              }
            />
          )}
        </LabelWrapper>
        {hasSaved && (
          <p className="text-sm text-muted-foreground">
            A value is already saved. Leave this blank to keep it.
          </p>
        )}
        {error && (
          <p
            data-testid="provider-connection-error"
            className="text-sm text-destructive min-w-0 [overflow-wrap:anywhere]"
          >
            {error}
          </p>
        )}
      </div>
    );
  };

  const azureConnectionFields = fields.filter(
    (field) => field.key === "api_base",
  );
  const azureAdvancedFields = fields.filter(
    (field) => field.key === "api_version",
  );
  const onPremConnectionFields = fields.filter(
    (field) => field.key === "api_base",
  );
  const onPremAdvancedFields = fields.filter((field) =>
    ["space_id", "project_id"].includes(field.key),
  );

  return (
    <div className="min-w-0 space-y-4">
      {provider === "azure" ? (
        <>
          {azureConnectionFields.map(renderField)}
          <Accordion
            type="single"
            value={azureAuthMethod ?? "api_key"}
            onValueChange={(method) =>
              method && onAzureAuthMethodChange?.(method)
            }
            className="space-y-2"
          >
            {AZURE_AUTH_GROUPS.map((group) => (
              <AccordionItem key={group.key} value={group.key}>
                <AccordionTrigger>
                  {group.label}
                  {group.key === "api_key" && (
                    <span className="ml-2 rounded bg-muted px-2 py-0.5 text-xs">
                      Recommended
                    </span>
                  )}
                </AccordionTrigger>
                <AccordionContent className="space-y-4">
                  {group.fields
                    .map((key) => fields.find((field) => field.key === key))
                    .filter((field): field is CatalogCredentialField =>
                      Boolean(field),
                    )
                    .map(renderField)}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
          <Accordion type="single" collapsible className="space-y-2">
            <AccordionItem value="advanced">
              <AccordionTrigger>Advanced settings</AccordionTrigger>
              <AccordionContent className="space-y-4">
                {azureAdvancedFields.map(renderField)}
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </>
      ) : provider === "watsonx_onprem" ? (
        <>
          {onPremConnectionFields.map(renderField)}
          <Accordion
            type="single"
            value={onPremAuthMethod ?? "username_api_key"}
            onValueChange={(method) =>
              method && onOnPremAuthMethodChange?.(method)
            }
            className="space-y-2"
          >
            {ON_PREM_AUTH_GROUPS.map((group) => (
              <AccordionItem key={group.key} value={group.key}>
                <AccordionTrigger>
                  {group.label}
                  {group.key === "username_api_key" && (
                    <span className="ml-2 rounded bg-muted px-2 py-0.5 text-xs">
                      Recommended
                    </span>
                  )}
                </AccordionTrigger>
                <AccordionContent className="space-y-4">
                  {group.fields
                    .map((key) => fields.find((field) => field.key === key))
                    .filter((field): field is CatalogCredentialField =>
                      Boolean(field),
                    )
                    .map(renderField)}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
          <Accordion type="single" collapsible className="space-y-2">
            <AccordionItem value="advanced">
              <AccordionTrigger>Advanced settings</AccordionTrigger>
              <AccordionContent className="space-y-4">
                {onPremAdvancedFields.map(renderField)}
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </>
      ) : (
        fields.map(renderField)
      )}
      {saveError && (
        <p
          data-testid="provider-connection-error"
          className="text-sm text-destructive min-w-0 [overflow-wrap:anywhere]"
        >
          {saveError}
        </p>
      )}
      <p className="text-sm text-muted-foreground">
        Pick the {providerName} models to use from the Agent and Ingestion
        settings after saving these credentials.
      </p>
    </div>
  );
}
