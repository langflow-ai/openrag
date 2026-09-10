import type { ReactNode } from "react";
import type { CatalogCredentialField } from "@/components/models/catalog-models";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  AZURE_AUTH_GROUPS,
  fieldsForKeys,
  ON_PREM_AUTH_GROUPS,
} from "./generic-provider-credential-fields.helpers";

export function GenericProviderCredentialFields({
  provider,
  fields,
  azureAuthMethod,
  onPremAuthMethod,
  onAzureAuthMethodChange,
  onOnPremAuthMethodChange,
  renderField,
}: {
  provider: string;
  fields: CatalogCredentialField[];
  azureAuthMethod: string;
  onPremAuthMethod: string;
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
              {fieldsForKeys(fields, ["space_id", "project_id"]).map(
                renderField,
              )}
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </>
    );
  }
  return <>{fields.map(renderField)}</>;
}
