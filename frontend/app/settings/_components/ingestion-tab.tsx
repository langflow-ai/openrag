"use client";

import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { isIngestPreviewEnabled } from "@/lib/ingest-preview";
import { IngestPreviewSettingsSection } from "./ingest-preview-settings-section";
import { IngestSettingsSection } from "./ingest-settings-section";

export function IngestionTab() {
  const { runMode } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  const showPreview = isIngestPreviewEnabled(runMode, { isCloudBrand });

  return (
    <div className="space-y-8">
      <IngestSettingsSection />
      {showPreview ? (
        <section className="space-y-4 border-t border-border pt-8">
          <h3 className="text-lg font-semibold leading-tight tracking-tight">
            Ingest preview
          </h3>
          <IngestPreviewSettingsSection />
        </section>
      ) : null}
    </div>
  );
}
