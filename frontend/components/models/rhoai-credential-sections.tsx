import type { ReactNode } from "react";
import type { CatalogCredentialField } from "@/components/models/catalog-models";
import {
  groupRhoaiFields,
  type RhoaiSectionsOpen,
} from "@/components/models/provider-credentials";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

/**
 * The Red Hat OpenShift AI credential form layout, shared by the Settings
 * dialog and onboarding: the chat endpoint and token up front, then the
 * collapsed "Embeddings" and "Advanced settings" sections.
 */
export function RhoaiCredentialSections({
  fields,
  renderField,
  openByDefault,
}: {
  fields: CatalogCredentialField[];
  renderField: (field: CatalogCredentialField) => ReactNode;
  openByDefault: RhoaiSectionsOpen;
}) {
  const { primary, embeddings, advanced } = groupRhoaiFields(fields);
  const defaultValue = [
    ...(openByDefault.embeddings ? ["embeddings"] : []),
    ...(openByDefault.advanced ? ["advanced"] : []),
  ];

  return (
    <>
      {primary.map(renderField)}
      {(embeddings.length > 0 || advanced.length > 0) && (
        <Accordion
          // Remounted when saved settings arrive after the first render, so a
          // saved value still opens its section.
          key={defaultValue.join(",") || "closed"}
          type="multiple"
          defaultValue={defaultValue}
          className="space-y-2"
        >
          {embeddings.length > 0 && (
            <AccordionItem value="embeddings">
              <AccordionTrigger>Embeddings</AccordionTrigger>
              <AccordionContent className="space-y-4">
                {embeddings.map(renderField)}
              </AccordionContent>
            </AccordionItem>
          )}
          {advanced.length > 0 && (
            <AccordionItem value="advanced">
              <AccordionTrigger>Advanced settings</AccordionTrigger>
              <AccordionContent className="space-y-4">
                {advanced.map(renderField)}
              </AccordionContent>
            </AccordionItem>
          )}
        </Accordion>
      )}
    </>
  );
}
