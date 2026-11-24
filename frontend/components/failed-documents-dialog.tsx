"use client";

import { Loader2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { useClearFailedIngestions } from "@/app/api/mutations/useClearFailedIngestions";
import { useFailedIngestionsQuery } from "@/app/api/queries/useFailedIngestionsQuery";
import { getConnectorLabel } from "@/lib/connectors/registry";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { ScrollArea } from "./ui/scroll-area";

interface FailedDocumentsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Lists documents that failed bucket ingestion with their last error, and lets
 * the user clear a failure ("Retry") so the next sync attempts the file again.
 * A file that changes at the source is retried automatically.
 */
export function FailedDocumentsDialog({
  open,
  onOpenChange,
}: FailedDocumentsDialogProps) {
  const { data, isLoading, error } = useFailedIngestionsQuery({
    enabled: open,
  });
  const clearMutation = useClearFailedIngestions();
  const failures = data?.failures ?? [];
  const maxAttempts = data?.max_attempts;

  const handleClear = async (request: {
    connectorType?: string;
    fileId?: string;
  }) => {
    try {
      const result = await clearMutation.mutateAsync(request);
      toast.success(
        result.cleared === 1
          ? "Cleared 1 failed document. Run a sync to retry it."
          : `Cleared ${result.cleared} failed documents. Run a sync to retry them.`,
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to clear failed documents",
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Failed documents</DialogTitle>
          <DialogDescription>
            Documents that could not be ingested.
            {maxAttempts
              ? ` After ${maxAttempts} failed attempts a document is skipped on later syncs until it changes at the source or you retry it.`
              : ""}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : error ? (
          <p className="py-4 text-sm text-destructive">
            {error instanceof Error
              ? error.message
              : "Failed to load failed documents"}
          </p>
        ) : failures.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No failed documents.
          </p>
        ) : (
          <ScrollArea className="max-h-96 pr-3">
            <ul className="divide-y divide-border">
              {failures.map((failure) => (
                <li
                  key={`${failure.connector_type}:${failure.file_id}`}
                  className="flex items-start gap-3 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium">
                        {failure.filename || failure.file_id}
                      </span>
                      <Badge variant="outline">
                        {getConnectorLabel(failure.connector_type) ??
                          failure.connector_type}
                      </Badge>
                      <Badge
                        variant={failure.skipped ? "destructive" : "secondary"}
                      >
                        {failure.skipped
                          ? "Skipped"
                          : `Attempt ${failure.attempt_count}${
                              maxAttempts ? ` of ${maxAttempts}` : ""
                            }`}
                      </Badge>
                    </div>
                    {failure.last_error && (
                      <p className="mt-1 break-words text-xs text-muted-foreground">
                        {failure.last_error}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-muted-foreground">
                      Last failed{" "}
                      {new Date(failure.last_failed_at).toLocaleString()}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={clearMutation.isPending}
                    onClick={() =>
                      handleClear({
                        connectorType: failure.connector_type,
                        fileId: failure.file_id,
                      })
                    }
                  >
                    <RotateCcw className="mr-2 h-3.5 w-3.5" />
                    Retry
                  </Button>
                </li>
              ))}
            </ul>
          </ScrollArea>
        )}

        <DialogFooter>
          {failures.length > 1 && (
            <Button
              type="button"
              variant="outline"
              disabled={clearMutation.isPending}
              onClick={() => handleClear({})}
            >
              Retry all
            </Button>
          )}
          <Button type="button" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
