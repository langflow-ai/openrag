"use client";

import { AlertCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useDismissFlowsUpdateMutation } from "@/app/api/mutations/useDismissFlowsUpdateMutation";
import { useUpdateFlowsMutation } from "@/app/api/mutations/useUpdateFlowsMutation";
import { useGetFlowsUpdatesQuery } from "@/app/api/queries/useGetFlowsUpdatesQuery";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { usePermissions } from "@/hooks/use-permissions";
import { formatFlowName } from "@/lib/utils";

export function FlowsUpdateDialog() {
  const { can } = usePermissions();
  const canEdit = can("flows:edit");
  const { data: updates, isLoading } = useGetFlowsUpdatesQuery({
    enabled: canEdit,
  });
  const updateMutation = useUpdateFlowsMutation();
  const dismissMutation = useDismissFlowsUpdateMutation();
  const [isOpen, setIsOpen] = useState(false);
  const [backupCustom, setBackupCustom] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const undismissedUpdates = updates?.filter((u) => !u.dismissed) ?? [];
  const hasUndismissed = undismissedUpdates.length > 0;

  useEffect(() => {
    if (!isLoading && hasUndismissed) {
      setIsOpen(true);
    } else if (!isLoading) {
      setIsOpen(false);
    }
  }, [isLoading, hasUndismissed]);

  const handleDismiss = async () => {
    setIsOpen(false);
    if (undismissedUpdates.length === 0) return;
    try {
      await dismissMutation.mutateAsync({
        flow_types: undismissedUpdates.map((u) => u.flow_type),
      });
    } catch (e) {
      console.error("Failed to dismiss flow updates", e);
    }
  };

  const handleUpdate = async () => {
    if (undismissedUpdates.length === 0) return;
    setErrorMessage(null);
    const flowTypes = undismissedUpdates.map((u) => u.flow_type);

    try {
      const results = await updateMutation.mutateAsync({
        flow_types: flowTypes,
        backup_custom: backupCustom,
      });

      const failed = results.filter((r) => !r.success);
      if (failed.length > 0) {
        const errorText = failed
          .map(
            (f) =>
              `${formatFlowName(f.flow_type)}: ${f.error || "Update failed"}`,
          )
          .join("; ");
        setErrorMessage(errorText);
        toast.error(`Flow update failed: ${errorText}`);
      } else {
        toast.success("Flows updated successfully");
        setIsOpen(false);
      }
    } catch (e: any) {
      const msg = e?.message || "Failed to update flows";
      setErrorMessage(msg);
      toast.error(msg);
    }
  };

  if (!can("flows:edit") || undismissedUpdates.length === 0) return null;

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Flow Updates Available</DialogTitle>
          <DialogDescription>
            There are updates available for your Langflow flows.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {errorMessage && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Update Failed</AlertTitle>
              <AlertDescription>{errorMessage}</AlertDescription>
            </Alert>
          )}

          <ul className="list-disc pl-4 space-y-1">
            {undismissedUpdates.map((update) => (
              <li key={update.flow_type}>
                <span className="font-medium">
                  {formatFlowName(update.flow_type)}
                </span>
              </li>
            ))}
          </ul>

          <Alert
            variant="default"
            className="border-yellow-500/50 bg-yellow-500/10"
          >
            <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-500" />
            <AlertTitle className="text-yellow-800 dark:text-yellow-400">
              Flow Updates Detected
            </AlertTitle>
            <AlertDescription className="text-yellow-700 dark:text-yellow-300">
              Updating will overwrite existing flows with newer versions. Backup
              flows will be created in Langflow so you can reference or redo
              your modifications.
            </AlertDescription>
          </Alert>

          <div className="flex items-center space-x-2 pt-2">
            <Checkbox
              id="backup-custom"
              checked={backupCustom}
              onCheckedChange={(checked) => setBackupCustom(!!checked)}
            />
            <label
              htmlFor="backup-custom"
              className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
            >
              Create backup flows in Langflow before updating
            </label>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleDismiss}>
            Skip for Now
          </Button>
          <Button onClick={handleUpdate} disabled={updateMutation.isPending}>
            {updateMutation.isPending ? "Updating..." : "Update Flows"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
