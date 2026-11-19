"use client";

import { Database } from "lucide-react";
import { useState } from "react";
import { useSnapshotStatusQuery } from "@/app/api/queries/useSnapshotStatusQuery";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { usePermissions } from "@/hooks/use-permissions";
import { trackButton } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import CardIcon from "../card-icon";
import { ImportWizard } from "./import-wizard";
import { ImportsList } from "./imports-list";

interface OpenSearchSnapshotCardProps {
  pollIntervalMs?: number;
}

/**
 * Connector card plus the list of imports. Renders nothing unless
 * `GET /status` reports the feature as enabled.
 */
export default function OpenSearchSnapshotCard({
  pollIntervalMs,
}: OpenSearchSnapshotCardProps) {
  const isCloudBrand = useIsCloudBrand();
  const { can } = usePermissions();
  const canCreate = can("connectors:create");
  const { data: status } = useSnapshotStatusQuery();
  // `null` = closed; "new" = fresh import; otherwise resume that import.
  const [wizard, setWizard] = useState<"new" | string | null>(null);

  if (!status?.enabled) return null;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Dataset Connectors</h3>
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <Card
          className={cn(
            "group relative flex flex-col transition-colors",
            isCloudBrand
              ? "rounded-none border-0 bg-layer-contextual text-layer-contextual-foreground shadow-none hover:bg-layer-contextual"
              : "hover:bg-secondary-hover hover:border-muted-foreground",
          )}
        >
          <CardHeader className="pb-2">
            <div className="mb-3">
              <CardIcon isActive activeBgColor="bg-white">
                <Database className="h-4 w-4" />
              </CardIcon>
            </div>
            <CardTitle
              className={cn(isCloudBrand && "text-layer-contextual-foreground")}
            >
              OpenSearch Snapshot
            </CardTitle>
            <CardDescription
              className={cn(
                "text-sm",
                isCloudBrand && "text-layer-contextual-foreground!",
              )}
            >
              Import indices from an OpenSearch snapshot in S3 as searchable
              datasets, without copying them into your documents.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col justify-end">
            <Button
              size="sm"
              className="w-full cursor-pointer"
              disabled={!canCreate}
              title={
                canCreate
                  ? undefined
                  : "You do not have permission to create connectors"
              }
              onClick={() => {
                trackButton({
                  CTA: "Import snapshot",
                  elementId: "import-opensearch-snapshot-button",
                  namespace: "settings",
                });
                setWizard("new");
              }}
            >
              Import snapshot
            </Button>
          </CardContent>
        </Card>
      </div>

      <ImportsList
        pollIntervalMs={pollIntervalMs}
        onOpenImport={(importId) => setWizard(importId)}
      />

      <ImportWizard
        open={wizard !== null}
        onOpenChange={(open) => {
          if (!open) setWizard(null);
        }}
        resumeImportId={wizard && wizard !== "new" ? wizard : null}
        pollIntervalMs={pollIntervalMs}
      />
    </div>
  );
}
