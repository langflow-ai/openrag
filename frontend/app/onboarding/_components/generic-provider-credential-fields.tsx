import type { ReactNode } from "react";
import { LabelInput } from "@/components/label-input";
import type { CatalogCredentialField } from "@/components/models/catalog-models";
import {
  AZURE_AUTH_GROUPS,
  fieldsForKeys,
  groupRhoaiFields,
  ON_PREM_AUTH_GROUPS,
  SECRET_REENTRY_HINT,
} from "@/components/models/provider-credentials";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

export function GenericProviderCredentialFields({
  provider,
  fields,
  azureAuthMethod,
  onPremAuthMethod,
  advancedOpenByDefault = false,
  onAzureAuthMethodChange,
  onOnPremAuthMethodChange,
  renderField,
}: {
  provider: string;
  fields: CatalogCredentialField[];
  azureAuthMethod: string;
  onPremAuthMethod: string;
  /** Start "Advanced settings" open (RHOAI: a saved non-default value). */
  advancedOpenByDefault?: boolean;
  onAzureAuthMethodChange: (method: string) => void;
  onOnPremAuthMethodChange: (method: string) => void;
  renderField: (field: CatalogCredentialField) => ReactNode;
}) {
  if (provider === "azure") {
    return (
      <>
        {fieldsForKeys(fields, ["api_base"]).map(renderField)}
        <Accordion
          type="single"
          value={azureAuthMethod}
          onValueChange={(method) => method && onAzureAuthMethodChange(method)}
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
                {fieldsForKeys(fields, group.fields).map(renderField)}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
        <Accordion type="single" collapsible className="space-y-2">
          <AccordionItem value="advanced">
            <AccordionTrigger>Advanced settings</AccordionTrigger>
            <AccordionContent className="space-y-4">
              {fieldsForKeys(fields, ["api_version"]).map(renderField)}
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </>
    );
  }
  if (provider === "watsonx_onprem") {
    return (
      <>
        {fieldsForKeys(fields, ["api_base"]).map(renderField)}
        <Accordion
          type="single"
          value={onPremAuthMethod}
          onValueChange={(method) => method && onOnPremAuthMethodChange(method)}
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
                {fieldsForKeys(fields, group.fields).map(renderField)}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
        <Accordion type="single" collapsible className="space-y-2">
          <AccordionItem value="advanced">
            <AccordionTrigger>Advanced settings</AccordionTrigger>
            <AccordionContent className="space-y-4">
              {fieldsForKeys(fields, [
                "ssl_verify",
                "space_id",
                "project_id",
              ]).map(renderField)}
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </>
    );
  }
  if (provider === "rhoai") {
    const { primary, advanced } = groupRhoaiFields(fields);
    return (
      <>
        {primary.map(renderField)}
        {advanced.length > 0 && (
          <Accordion
            // Remounted when saved settings arrive after the first render, so
            // a saved advanced value still opens the section.
            key={advancedOpenByDefault ? "advanced-open" : "advanced-closed"}
            type="single"
            collapsible
            defaultValue={advancedOpenByDefault ? "advanced" : undefined}
            className="space-y-2"
          >
            <AccordionItem value="advanced">
              <AccordionTrigger>Advanced settings</AccordionTrigger>
              <AccordionContent className="space-y-4">
                {advanced.map(renderField)}
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        )}
      </>
    );
  }
  return <>{fields.map(renderField)}</>;
}

/**
 * One catalogue-described credential input, with the hints for a saved secret
 * that may be kept or must be entered again.
 */
export function GenericCredentialInput({
  field,
  id,
  value,
  hasSavedSecret,
  needsReentry,
  onChange,
}: {
  field: CatalogCredentialField;
  id: string;
  value: string;
  /** A saved value for this key may be reused (the target is unchanged). */
  hasSavedSecret: boolean;
  needsReentry: boolean;
  onChange: (value: string) => void;
}) {
  const isSecret =
    field.field_type === "password" || field.field_type === "textarea";
  const hasSaved = isSecret && hasSavedSecret;
  return (
    <div className="space-y-1">
      <LabelInput
        label={field.label}
        helperText={field.tooltip ?? ""}
        id={id}
        type={field.field_type === "password" ? "password" : "text"}
        required={field.required && !hasSaved}
        placeholder={hasSaved ? "•••••••••" : (field.placeholder ?? undefined)}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {hasSaved && (
        <p className="text-mmd text-muted-foreground">
          A value is already saved. Leave this blank to keep it.
        </p>
      )}
      {needsReentry && (
        <p className="text-mmd text-muted-foreground">{SECRET_REENTRY_HINT}</p>
      )}
    </div>
  );
}
