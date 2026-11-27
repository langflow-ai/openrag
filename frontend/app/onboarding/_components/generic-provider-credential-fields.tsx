import type { ReactNode } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import type { CatalogCredentialField } from "@/components/models/catalog-models";
import {
  AZURE_AUTH_GROUPS,
  fieldsForKeys,
  ON_PREM_AUTH_GROUPS,
  type RhoaiSectionsOpen,
  SECRET_REENTRY_HINT,
} from "@/components/models/provider-credentials";
import { RhoaiCredentialSections } from "@/components/models/rhoai-credential-sections";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Textarea } from "@/components/ui/textarea";

const RHOAI_SECTIONS_CLOSED: RhoaiSectionsOpen = {
  embeddings: false,
  advanced: false,
};

export function GenericProviderCredentialFields({
  provider,
  fields,
  azureAuthMethod,
  onPremAuthMethod,
  rhoaiOpenByDefault = RHOAI_SECTIONS_CLOSED,
  onAzureAuthMethodChange,
  onOnPremAuthMethodChange,
  renderField,
}: {
  provider: string;
  fields: CatalogCredentialField[];
  azureAuthMethod: string;
  onPremAuthMethod: string;
  /** Which RHOAI sections start open. */
  rhoaiOpenByDefault?: RhoaiSectionsOpen;
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
    return (
      <RhoaiCredentialSections
        fields={fields}
        renderField={renderField}
        openByDefault={rhoaiOpenByDefault}
      />
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
      {field.field_type === "textarea" ? (
        // A single-line input strips the newlines of a pasted PEM key.
        <LabelWrapper
          label={field.label}
          helperText={field.tooltip ?? ""}
          id={id}
          required={field.required && !hasSaved}
        >
          <Textarea
            id={id}
            data-testid={id}
            required={field.required && !hasSaved}
            placeholder={
              hasSaved ? "•••••••••" : (field.placeholder ?? undefined)
            }
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        </LabelWrapper>
      ) : (
        <LabelInput
          label={field.label}
          helperText={field.tooltip ?? ""}
          id={id}
          type={field.field_type === "password" ? "password" : "text"}
          required={field.required && !hasSaved}
          placeholder={
            hasSaved ? "•••••••••" : (field.placeholder ?? undefined)
          }
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
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
