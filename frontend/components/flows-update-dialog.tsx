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

interface FlowsUpdateDialogProps {
  overrideOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function FlowsUpdateDialog({
  overrideOpen,
  onOpenChange,
}: FlowsUpdateDialogProps = {}) {
  const { can } = usePermissions();
  const canEdit = can("flows:edit");
  const { data: updates, isLoading } = useGetFlowsUpdatesQuery({
    enabled: canEdit,
  });
  const updateMutation = useUpdateFlowsMutation();
  const dismissMutation = useDismissFlowsUpdateMutation();
  const [internalIsOpen, setInternalIsOpen] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [backupCustom, setBackupCustom] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const isOpen = overrideOpen ?? internalIsOpen;
  const setIsOpen = (open: boolean) => {
    setInternalIsOpen(open);
    onOpenChange?.(open);
  };

  const undismissedUpdates = updates?.filter((u) => !u.dismissed) ?? [];
  const hasUndismissed = undismissedUpdates.length > 0;

  const [prevIsLoading, setPrevIsLoading] = useState(isLoading);
  const [prevHasUndismissed, setPrevHasUndismissed] = useState(hasUndismissed);

  if (isLoading !== prevIsLoading || hasUndismissed !== prevHasUndismissed) {
    setPrevIsLoading(isLoading);
    setPrevHasUndismissed(hasUndismissed);
    if (overrideOpen === undefined) {
      if (!isLoading && hasUndismissed) {
        setInternalIsOpen(true);
      } else if (!isLoading) {
        setInternalIsOpen(false);
      }
    }
  }

  const handleDismiss = async () => {
    setIsOpen(false);
    setShowConfirm(false);
    if (undismissedUpdates.length === 0) return;
    try {
      await dismissMutation.mutateAsync({
        flow_types: undismissedUpdates.map((u) => u.flow_type),
      });
    } catch (e) {
      console.error("Failed to dismiss flow updates", e);
    }
  };

  const handleInitialUpdateClick = () => {
    setIsOpen(false);
    setShowConfirm(true);
  };

  const handleConfirmUpdate = async () => {
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
        setShowConfirm(false);
      }
    } catch (e: any) {
      const msg = e?.message || "Failed to update flows";
      setErrorMessage(msg);
      toast.error(msg);
    }
  };

  if (
    !can("flows:edit") ||
    (overrideOpen === undefined && undismissedUpdates.length === 0)
  )
    return null;

  return (
    <>
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="sm:max-w-[540px]">
          <DialogHeader>
            <DialogTitle>Update required from Langflow</DialogTitle>
            <DialogDescription>
              OpenRAG will back up your customized flows first
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {errorMessage && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>Update Failed</AlertTitle>
                <AlertDescription>{errorMessage}</AlertDescription>
              </Alert>
            )}

            <p className="text-sm text-muted-foreground leading-relaxed">
              Updating Langflow discards your customizations to OpenRAG flows.
              OpenRAG copies the core flows before updating, so you can reapply
              your changes afterward. OpenRAG stores the copies in its embedded
              Langflow instance.
            </p>

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
                Back up my flows in Langflow before updating
              </label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={handleDismiss}>
              Skip action
            </Button>
            <Button onClick={handleInitialUpdateClick}>Update flow</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showConfirm} onOpenChange={setShowConfirm}>
        <DialogContent className="sm:max-w-[540px]">
          <DialogHeader>
            <DialogTitle>Confirm Langflow Update</DialogTitle>
          </DialogHeader>

          <div className="py-2">
            <p className="text-sm text-muted-foreground leading-relaxed">
              Updating Langflow will overwrite any custom changes made. Backup
              copies of your flows will be created located in Langflow, Do you
              want to continue?
            </p>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConfirm(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleConfirmUpdate}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? "Updating..." : "Continue update"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
