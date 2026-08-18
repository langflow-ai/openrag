"use client";

import { Archive, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { useGetArchivingSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { formatFileSize } from "@/lib/file-format";

export function ArchivingSettingsSection() {
  const { data: settings, isLoading } = useGetArchivingSettingsQuery();
  const serverEnabled = settings?.archiving?.enabled ?? false;
  const [draftEnabled, setDraftEnabled] = useState<boolean | null>(null);
  const enabled = draftEnabled ?? serverEnabled;
  const archive = settings?.archiving;
  const isDirty = draftEnabled !== null && draftEnabled !== serverEnabled;

  const updateSettings = useUpdateSettingsMutation({
    onSuccess: () => {
      setDraftEnabled(null);
      toast.success("Archiving settings updated");
    },
    onError: (error) => toast.error(error.message),
  });

  return (
    <Card data-testid="archiving-settings">
      <CardHeader>
        <div className="flex items-center gap-3">
          <Archive className="h-5 w-5 text-muted-foreground" />
          <div>
            <CardTitle>Source archiving</CardTitle>
            <CardDescription className="mt-1">
              {archive?.available === false
                ? "Local source storage is unavailable in multi-user mode."
                : "Keep successful local uploads as downloadable originals and add their authenticated URL to search and chat citations."}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {archive?.available === false ? (
          <div className="rounded-lg border p-4 text-sm text-muted-foreground">
            Uploads remain available through the authenticated document API,
            with or without a remote <code>source_url</code>. OpenRAG does not
            read server-local paths or retain uploaded bytes on local storage in
            this mode.
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
              <div>
                <Label htmlFor="archive-sources-enabled" className="text-base">
                  Keep original source files
                </Label>
                <p className="mt-1 text-sm text-muted-foreground">
                  Successfully indexed files are moved to the archive. Sources
                  that already came from the ingestion folder are restored
                  there if processing fails. When disabled, folder sources stay
                  in place, browser uploads are not copied, and citations have
                  no local download link.
                </p>
              </div>
              <Switch
                id="archive-sources-enabled"
                checked={enabled}
                disabled={isLoading || updateSettings.isPending}
                onCheckedChange={setDraftEnabled}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="source-ingestion-path">Ingestion folder</Label>
              <Input
                id="source-ingestion-path"
                value={
                  archive?.ingestion_host_path ??
                  archive?.ingestion_path ??
                  "Loading…"
                }
                readOnly
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Drop local files here, then start “Ingestion folder” from Add
                Knowledge. Configure this path with OPENRAG_DOCUMENTS_PATH.
                {archive?.ingestion_host_path && (
                  <> Container path: {archive.ingestion_path}.</>
                )}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="source-archive-path">Archive location</Label>
              <Input
                id="source-archive-path"
                value={archive?.host_path ?? archive?.path ?? "Loading…"}
                readOnly
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Configure the deployment path with
                OPENRAG_INDEXED_DOCUMENTS_PATH.
                {archive?.host_path && <> Container path: {archive.path}.</>}
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <ArchiveMetric
                label="Archive used"
                value={formatFileSize(archive?.used_bytes)}
              />
              <ArchiveMetric
                label="Filesystem capacity"
                value={formatFileSize(archive?.filesystem_total_bytes)}
              />
              <ArchiveMetric
                label="Filesystem free"
                value={formatFileSize(archive?.filesystem_free_bytes)}
              />
            </div>
          </>
        )}

        <div className="rounded-lg bg-muted/30 p-4 text-sm text-muted-foreground">
          API clients can keep a remote source instead: send an HTTP(S){" "}
          <code>source_url</code> with <code>archive_source=false</code>. OpenRAG
          stores the URL in citations without copying the remote file.
        </div>

        {archive?.available !== false && (
          <div className="flex justify-end">
            <Button
              disabled={!isDirty || updateSettings.isPending}
              onClick={() =>
                updateSettings.mutate({ archive_sources_enabled: enabled })
              }
            >
              {updateSettings.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Save changes
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ArchiveMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-medium">{value}</p>
    </div>
  );
}
