"use client";

import { AlertCircle, AlertTriangle } from "lucide-react";
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
import { useAuth } from "@/contexts/auth-context";
import { useOnboardingState } from "@/hooks/use-onboarding-state";
import { formatFlowName } from "@/lib/utils";

interface FlowsUpdateDialogProps {
  overrideOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  isOnboarding?: boolean;
}

export function FlowsUpdateDialog({
  overrideOpen,
  onOpenChange,
  isOnboarding: propIsOnboarding,
}: FlowsUpdateDialogProps = {}) {
  const { roles, isNoAuthMode, rbacEnforced, can } = useAuth();
  const isAdmin =
    isNoAuthMode ||
    !rbacEnforced ||
    roles.includes("admin") ||
    can("config:write");

  const { isOnboardingComplete } = useOnboardingState();
  const isOnboarding = propIsOnboarding ?? !isOnboardingComplete;

  const { data: updates, isLoading } = useGetFlowsUpdatesQuery({
    enabled: true,
  });
  const updateMutation = useUpdateFlowsMutation();
  const dismissMutation = useDismissFlowsUpdateMutation();
  const [internalIsOpen, setInternalIsOpen] = useState(false);
  const [showSkipConfirm, setShowSkipConfirm] = useState(false);
  const [showUpdateConfirm, setShowUpdateConfirm] = useState(false);
  const [isUpdatingWithBackup, setIsUpdatingWithBackup] = useState<
    boolean | null
  >(null);
  const [backupCustom, setBackupCustom] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const allUpdates = updates ?? [];
  const undismissedUpdates = allUpdates.filter((u) => !u.dismissed);
  const targetUpdates =
    undismissedUpdates.length > 0 ? undismissedUpdates : allUpdates;
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

  const isMainOpen =
    !showSkipConfirm && !showUpdateConfirm && (overrideOpen ?? internalIsOpen);

  const handleClose = () => {
    setInternalIsOpen(false);
    setShowSkipConfirm(false);
    setShowUpdateConfirm(false);
    setIsUpdatingWithBackup(null);
    onOpenChange?.(false);
  };

  const handleDismiss = async () => {
    handleClose();
    if (targetUpdates.length === 0) return;
    try {
      await dismissMutation.mutateAsync({
        flow_types: targetUpdates.map((u) => u.flow_type),
      });
    } catch (e) {
      console.error("Failed to dismiss flow updates", e);
    }
  };

  const handleSkipClick = () => {
    setShowSkipConfirm(true);
  };

  const handleSkipConfirmOpenChange = (open: boolean) => {
    setShowSkipConfirm(open);
  };

  const handleInitialUpdateClick = () => {
    if (!backupCustom) {
      setShowUpdateConfirm(true);
    } else {
      handleConfirmUpdate(true);
    }
  };

  const handleConfirmUpdate = async (withBackup: boolean) => {
    if (targetUpdates.length === 0) return;
    setErrorMessage(null);
    setIsUpdatingWithBackup(withBackup);
    const flowTypes = targetUpdates.map((u) => u.flow_type);

    try {
      const results = await updateMutation.mutateAsync({
        flow_types: flowTypes,
        backup_custom: withBackup,
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
        setShowUpdateConfirm(false);
        setInternalIsOpen(true);
      } else {
        toast.success("Flows updated successfully");
        handleClose();
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to update flows";
      setErrorMessage(msg);
      toast.error(msg);
      setShowUpdateConfirm(false);
      setInternalIsOpen(true);
    } finally {
      setIsUpdatingWithBackup(null);
    }
  };

  if (targetUpdates.length === 0) return null;
  if (overrideOpen === undefined && undismissedUpdates.length === 0)
    return null;

  if (!isAdmin) {
    return (
      <Dialog open={isMainOpen} onOpenChange={(open) => !open && handleClose()}>
        <DialogContent className="sm:max-w-[540px]">
          <DialogHeader>
            <DialogTitle>Langflow flow updates available</DialogTitle>
            <DialogDescription>
              Action required by an administrator
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Updates Available</AlertTitle>
              <AlertDescription className="text-muted-foreground leading-relaxed">
                New versions of one or more Langflow flows are available. An
                administrator must review and apply the updates. Until then,
                some flows might not work as expected.
              </AlertDescription>
            </Alert>
          </div>

          <DialogFooter>
            <Button onClick={handleDismiss}>
              <div>Understood</div>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <>
      <Dialog open={isMainOpen} onOpenChange={(open) => !open && handleClose()}>
        <DialogContent className="sm:max-w-[540px]">
          <DialogHeader>
            <DialogTitle>Update Langflow flows</DialogTitle>
            <DialogDescription>
              New versions of one or more Langflow flows are available.
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

            <div className="space-y-3 text-sm text-muted-foreground leading-relaxed">
              <p>
                If you have customized any flows, those customizations will be
                removed during the update.
              </p>
              <p>
                By default, OpenRAG backs up customized flows and stores the
                backups in its embedded Langflow instance. After the update, you
                can use the backups to manually reapply your customizations.
              </p>
              <p>
                If you don&apos;t have customized flows, a backup isn&apos;t
                required.
              </p>
            </div>

            <div className="flex items-center space-x-2 pt-2">
              <Checkbox
                id="backup-custom"
                checked={backupCustom}
                onCheckedChange={(checked) => setBackupCustom(!!checked)}
              />
              <label
                htmlFor="backup-custom"
                className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
              >
                Back up my flows before updating
              </label>
            </div>
          </div>

          <DialogFooter>
            {!isOnboarding && (
              <Button
                variant="outline"
                onClick={handleSkipClick}
                disabled={updateMutation.isPending || dismissMutation.isPending}
              >
                <div>Skip update</div>
              </Button>
            )}
            <Button
              onClick={handleInitialUpdateClick}
              disabled={updateMutation.isPending || dismissMutation.isPending}
            >
              <div>
                {updateMutation.isPending ? "Updating..." : "Update flows"}
              </div>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showSkipConfirm} onOpenChange={handleSkipConfirmOpenChange}>
        <DialogContent className="sm:max-w-[540px]">
          <DialogHeader>
            <DialogTitle>Skip the Langflow update</DialogTitle>
            <DialogDescription className="sr-only">
              Skip the Langflow update confirmation
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2 text-sm text-muted-foreground leading-relaxed">
            <p>
              OpenRAG flows are designed to work with the latest supported
              version of Langflow.
            </p>
            <p>
              If you skip this update, some flows might become incompatible and
              stop working correctly.
            </p>
          </div>

          <DialogFooter>
            <Button
              onClick={() => {
                setShowSkipConfirm(false);
                if (!backupCustom) {
                  setShowUpdateConfirm(true);
                } else {
                  handleConfirmUpdate(true);
                }
              }}
              disabled={updateMutation.isPending || dismissMutation.isPending}
            >
              <div>Update flows</div>
            </Button>
            <Button
              variant="outline"
              onClick={handleDismiss}
              disabled={updateMutation.isPending || dismissMutation.isPending}
            >
              <div>
                {dismissMutation.isPending ? "Skipping..." : "Skip update"}
              </div>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showUpdateConfirm} onOpenChange={setShowUpdateConfirm}>
        <DialogContent className="sm:max-w-[540px]">
          <DialogHeader>
            <DialogTitle>Update without a backup</DialogTitle>
            <DialogDescription className="sr-only">
              Update without a backup confirmation
            </DialogDescription>
          </DialogHeader>

          <div className="py-2 text-sm text-muted-foreground leading-relaxed">
            <p>
              If you&apos;ve customized any OpenRAG flows, updating without a
              backup permanently removes those customizations. You won&apos;t be
              able to restore them after the update.
            </p>
          </div>

          <DialogFooter>
            <Button
              onClick={() => {
                setBackupCustom(true);
                handleConfirmUpdate(true);
              }}
              disabled={updateMutation.isPending}
            >
              <div>
                {updateMutation.isPending && isUpdatingWithBackup
                  ? "Updating..."
                  : "Back up my flows"}
              </div>
            </Button>
            <Button
              variant="outline"
              onClick={() => handleConfirmUpdate(false)}
              disabled={updateMutation.isPending}
            >
              <div>
                {updateMutation.isPending && isUpdatingWithBackup === false
                  ? "Updating..."
                  : "Continue without backup"}
              </div>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
