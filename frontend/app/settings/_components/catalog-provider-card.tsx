"use client";

import { Button } from "@/components/ui/button";
import { trackButton } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { getModelLogo } from "../_helpers/model-helpers";

interface CatalogProviderCardProps {
  providerKey: string;
  name: string;
  isConfigured: boolean;
  onConfigure: (providerKey: string) => void;
}

/**
 * Box for a LiteLLM catalogue provider — the ones without a bespoke settings
 * dialog. Rendered for every provider the installed LiteLLM version supports,
 * so the whole list is browsable on the page instead of hidden behind a
 * dropdown.
 */
export default function CatalogProviderCard({
  providerKey,
  name,
  isConfigured,
  onConfigure,
}: CatalogProviderCardProps) {
  return (
    <div
      className={cn(
        "group flex min-h-40 flex-col justify-between border p-4 transition-colors",
        isConfigured
          ? "hover:border-muted-foreground hover:bg-secondary-hover"
          : "text-muted-foreground hover:border-muted-foreground hover:bg-secondary-hover",
      )}
    >
      <div>
        <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-md bg-white">
          {getModelLogo("", providerKey)}
        </div>
        <p className="font-medium break-all">{name}</p>
        <p className="text-mmd text-muted-foreground">
          {isConfigured ? "Configured" : "Not configured"}
        </p>
      </div>
      <Button
        className="group-hover:bg-background"
        variant="outline"
        onClick={() => {
          trackButton({
            CTA: `${isConfigured ? "Edit Setup" : "Configure"} - ${name}`,
            elementId: "catalog-provider-card-button",
            namespace: "settings",
            payload: { provider: providerKey },
          });
          onConfigure(providerKey);
        }}
      >
        {isConfigured ? "Edit setup" : "Configure"}
      </Button>
    </div>
  );
}
