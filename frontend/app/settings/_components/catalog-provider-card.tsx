"use client";

import Image from "next/image";
import { Button } from "@/components/ui/button";
import { trackButton } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { providerLogo, providerMonogram } from "../_helpers/provider-logos";
import CardIcon from "./card-icon";

interface CatalogProviderCardProps {
  providerKey: string;
  name: string;
  isConfigured: boolean;
  onConfigure: (providerKey: string) => void;
}

/**
 * Provider mark sized to match the built-in cards' logos.
 *
 * ``getModelLogo`` renders an 11px image inside a 16px frame because it is
 * built for dropdown rows; dropped into a card tile it looks tiny next to the
 * bespoke provider SVGs, which draw at ~17px. Render the mark directly at that
 * size so both grids line up.
 */
function ProviderMark({ providerKey }: { providerKey: string }) {
  const logo = providerLogo(providerKey);

  if (!logo) {
    return (
      <span className="font-semibold text-[11px] text-muted-foreground">
        {providerMonogram(providerKey)}
      </span>
    );
  }

  return (
    <Image
      src={logo}
      alt=""
      width={17}
      height={17}
      className="h-[17px] w-[17px] object-contain"
    />
  );
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
        "group flex min-h-40 flex-col justify-between border p-4 transition-colors hover:border-muted-foreground hover:bg-secondary-hover",
        !isConfigured && "text-muted-foreground",
      )}
    >
      <div>
        <div className="mb-3">
          <CardIcon isActive={isConfigured} activeBgColor="bg-white">
            <ProviderMark providerKey={providerKey} />
          </CardIcon>
        </div>
        <p className="break-all font-medium">{name}</p>
        <p className="text-mmd text-muted-foreground">
          {isConfigured ? "Configured" : "Not configured"}
        </p>
      </div>
      <Button
        className="mt-4 group-hover:bg-background"
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
