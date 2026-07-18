"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/settings-tabs";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  INGEST_PREVIEW_AUTO_OPEN_OPTIONS,
  type IngestPreviewAutoOpen,
} from "@/hooks/use-ingest-preview-settings";
import { cn } from "@/lib/utils";

export function IngestPreviewAutoOpenControl({
  value,
  onChange,
  "aria-label": ariaLabel = "Auto-open on ingest",
  className,
}: {
  value: IngestPreviewAutoOpen;
  onChange: (value: IngestPreviewAutoOpen) => void;
  "aria-label"?: string;
  className?: string;
}) {
  const isCloudBrand = useIsCloudBrand();

  return (
    <Tabs
      value={value}
      onValueChange={(next) => onChange(next as IngestPreviewAutoOpen)}
      className={className}
    >
      <TabsList
        variant="default"
        aria-label={ariaLabel}
        className={cn(
          "h-auto shrink-0 border border-border p-0.5",
          isCloudBrand ? "!rounded-none overflow-hidden" : "rounded-md",
        )}
      >
        {INGEST_PREVIEW_AUTO_OPEN_OPTIONS.map((option) => (
          <TabsTrigger
            key={option.value}
            value={option.value}
            className={cn(
              "px-3 py-1.5 text-xs sm:text-sm",
              isCloudBrand &&
                "!rounded-none dark:hover:!bg-[#F4F4F4] dark:hover:!text-neutral-900 dark:data-[state=active]:!bg-[#F4F4F4] dark:data-[state=active]:!text-neutral-900",
              isCloudBrand &&
                option.value === "first-run" &&
                "!border-y-0 !border-l !border-r !border-border",
            )}
          >
            {option.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
