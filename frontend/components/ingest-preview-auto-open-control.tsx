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
          "grid !h-9 w-[220px] shrink-0 grid-cols-2 items-stretch gap-0 !p-0",
          "border border-border !bg-transparent",
          isCloudBrand
            ? "rounded-none overflow-hidden"
            : "rounded-md overflow-hidden",
        )}
      >
        {INGEST_PREVIEW_AUTO_OPEN_OPTIONS.map((option) => (
          <TabsTrigger
            key={option.value}
            value={option.value}
            className={cn(
              "!flex !h-full !min-h-0 items-center justify-center",
              "!rounded-none !border-0 !px-3 !py-0 !leading-none text-sm font-medium",
              "!shadow-none text-muted-foreground hover:text-foreground",
              "hover:!bg-transparent data-[state=active]:!shadow-none",
              "data-[state=active]:!bg-muted data-[state=active]:!text-foreground",
              "dark:hover:!bg-transparent dark:hover:!text-foreground",
              "dark:data-[state=active]:!bg-white/10 dark:data-[state=active]:!text-foreground",
              "dark:focus-visible:!bg-white/10 dark:focus-visible:!text-foreground",
              option.value === "every" && "!border-r !border-border",
            )}
          >
            {option.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
