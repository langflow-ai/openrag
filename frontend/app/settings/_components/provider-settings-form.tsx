import { useFormContext } from "react-hook-form";
import type { CatalogCredentialField } from "@/app/settings/_helpers/catalog-models";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export interface ProviderSettingsFormData {
  credentials: Record<string, string>;
}

/**
 * Credential form for a provider with no bespoke dialog, rendered from the
 * field spec `/api/models/catalog` publishes for it. A provider added to
 * `config/model_providers.yaml` is configurable through this without any
 * further frontend work.
 */
export function ProviderSettingsForm({
  providerName,
  fields,
  savedSecretFields,
  saveError,
}: {
  providerName: string;
  fields: CatalogCredentialField[];
  savedSecretFields: string[];
  saveError?: string | null;
}) {
  const {
    register,
    formState: { errors },
  } = useFormContext<ProviderSettingsFormData>();

  const saved = new Set(savedSecretFields);

  return (
    <div className="min-w-0 space-y-4">
      {fields.map((field) => {
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
      })}
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
