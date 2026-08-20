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
    <div className="space-y-6">
      <IngestSettingsSection />
      {showPreview ? (
        <div className="space-y-4">
          <h2 className="text-lg font-medium">Ingest preview</h2>
          <IngestPreviewSettingsSection />
        </div>
      ) : null}
    </div>
  );
}
