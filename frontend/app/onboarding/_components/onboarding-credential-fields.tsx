"use client";

import { useEffect, useMemo, useState } from "react";
import type { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";
import type { ModelCatalogResponse } from "@/app/api/queries/useGetModelsQuery";
import {
  onboardingCredentialFields,
  type SettingsCatalogProvider,
} from "@/app/settings/_helpers/catalog-models";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const SECRET_TYPES = new Set(["password", "textarea", "upload"]);

export interface CredentialStatus {
  ready: boolean;
  isValidating: boolean;
  hasError: boolean;
}

interface Props {
  provider: SettingsCatalogProvider;
  catalog: ModelCatalogResponse | undefined;
  savedValues?: Record<string, string>;
  savedSecretFields?: string[];
  setSettings: React.Dispatch<React.SetStateAction<OnboardingVariables>>;
  onStatusChange: (status: CredentialStatus) => void;
}

function optionValues(options: unknown): string[] {
  if (!Array.isArray(options)) return [];
  return options.flatMap((option) => {
    if (typeof option === "string") return [option];
    if (
      option &&
      typeof option === "object" &&
      "value" in option &&
      typeof option.value === "string"
    ) {
      return [option.value];
    }
    return [];
  });
}

export function OnboardingCredentialFields({
  provider,
  catalog,
  savedValues,
  savedSecretFields = [],
  setSettings,
  onStatusChange,
}: Props) {
  const fields = useMemo(
    () => onboardingCredentialFields(catalog, provider),
    [catalog, provider],
  );
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial = { ...(savedValues ?? {}) };
    for (const field of fields) {
      if (
        initial[field.key] === undefined &&
        typeof field.default_value === "string"
      ) {
        initial[field.key] = field.default_value;
      }
    }
    return initial;
  });
  const savedSecrets = useMemo(
    () => new Set(savedSecretFields),
    [savedSecretFields],
  );

  useEffect(() => {
    setSettings((previous) => ({
      ...previous,
      provider_credentials: {
        ...(previous.provider_credentials ?? {}),
        [provider]: Object.fromEntries(
          Object.entries(values).filter(([, value]) => value.trim()),
        ),
      },
    }));
  }, [provider, setSettings, values]);

  useEffect(() => {
    const ready = fields
      .filter((field) => field.required)
      .every(
        (field) =>
          Boolean(values[field.key]?.trim()) || savedSecrets.has(field.key),
      );
    onStatusChange({ ready, isValidating: false, hasError: false });
  }, [fields, onStatusChange, savedSecrets, values]);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {fields.map((field) => {
        const id = `credential-${field.key}`;
        const options = optionValues(field.options);
        const value = values[field.key] ?? "";
        const setValue = (next: string) =>
          setValues((previous) => ({ ...previous, [field.key]: next }));
        const helper = field.tooltip || undefined;
        const reusingSecret = savedSecrets.has(field.key) && !value;

        if (field.field_type === "select" && options.length > 0) {
          return (
            <LabelWrapper
              key={field.key}
              id={id}
              label={field.label}
              helperText={helper}
              required={field.required}
            >
              <Select value={value} onValueChange={setValue}>
                <SelectTrigger id={id} data-testid={id}>
                  <SelectValue
                    placeholder={field.placeholder ?? `Choose ${field.label}`}
                  />
                </SelectTrigger>
                <SelectContent>
                  {options.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </LabelWrapper>
          );
        }

        if (field.field_type === "textarea" || field.field_type === "upload") {
          return (
            <LabelWrapper
              key={field.key}
              id={id}
              label={field.label}
              helperText={helper}
              required={field.required}
            >
              <div className="space-y-1">
                <Textarea
                  id={id}
                  data-testid={id}
                  value={value}
                  placeholder={
                    reusingSecret
                      ? "Configured secret (leave blank to reuse)"
                      : (field.placeholder ?? undefined)
                  }
                  onChange={(event) => setValue(event.target.value)}
                />
                {reusingSecret && (
                  <p className="text-mmd text-muted-foreground">
                    Leave blank to reuse the configured secret.
                  </p>
                )}
              </div>
            </LabelWrapper>
          );
        }

        return (
          <LabelWrapper
            key={field.key}
            id={id}
            label={field.label}
            helperText={helper}
            required={field.required}
          >
            <div className="space-y-1">
              <Input
                id={id}
                data-testid={id}
                type={SECRET_TYPES.has(field.field_type) ? "password" : "text"}
                value={value}
                placeholder={
                  reusingSecret
                    ? "Configured secret (leave blank to reuse)"
                    : (field.placeholder ?? undefined)
                }
                onChange={(event) => setValue(event.target.value)}
              />
              {reusingSecret && (
                <p className="text-mmd text-muted-foreground">
                  Leave blank to reuse the configured secret.
                </p>
              )}
            </div>
          </LabelWrapper>
        );
      })}
    </div>
  );
}
