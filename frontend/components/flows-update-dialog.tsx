"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useDismissFlowsUpdateMutation } from "@/app/api/mutations/useDismissFlowsUpdateMutation";
import { useUpdateFlowsMutation } from "@/app/api/mutations/useUpdateFlowsMutation";
import { useGetFlowsUpdatesQuery } from "@/app/api/queries/useGetFlowsUpdatesQuery";
import { AdminUpdateDialog } from "@/components/flows-update-dialog/admin-update-dialog";
import { NonAdminUpdateDialog } from "@/components/flows-update-dialog/non-admin-update-dialog";
import { SkipUpdateConfirmDialog } from "@/components/flows-update-dialog/skip-update-confirm-dialog";
import { UpdateWithoutBackupDialog } from "@/components/flows-update-dialog/update-without-backup-dialog";
import { useOnboardingState } from "@/hooks/use-onboarding-state";
import { useSettingsTabAccess } from "@/hooks/use-permissions";
import { canManageFlowUpdates, canViewFlowUpdates } from "@/lib/brand";
import { formatFlowName } from "@/lib/utils";

const SESSION_DISMISSED_KEY = "openrag_flows_update_dismissed_session";

function hasDismissedFlowsUpdateInSession() {
  if (typeof window === "undefined") return false;
  try {
    return Boolean(sessionStorage.getItem(SESSION_DISMISSED_KEY));
  } catch {
    return false;
  }
}

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
  const tabAccess = useSettingsTabAccess();
  const isAdmin = canManageFlowUpdates(tabAccess);
  const canView = canViewFlowUpdates(tabAccess);

  const { isOnboardingComplete } = useOnboardingState();
  const isOnboarding = propIsOnboarding ?? !isOnboardingComplete;

  const { data: updates, isLoading } = useGetFlowsUpdatesQuery({
    enabled: canView,
  });
  const updateMutation = useUpdateFlowsMutation();
  const dismissMutation = useDismissFlowsUpdateMutation();
  const [closedUpdateKey, setClosedUpdateKey] = useState<string | null>(null);
  const [isSessionDismissed, setIsSessionDismissed] = useState(
    hasDismissedFlowsUpdateInSession,
  );
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
  const currentUpdateKey = targetUpdates
    .map((update) => `${update.flow_type}:${update.flow_id}`)
    .sort()
    .join("|");
  const isAutoOpen =
    !isLoading && hasUndismissed && closedUpdateKey !== currentUpdateKey;

  const isMainOpen =
    !showSkipConfirm &&
    !showUpdateConfirm &&
    (overrideOpen ?? (isAutoOpen && !(!isAdmin && isSessionDismissed)));

  const handleClose = () => {
    if (currentUpdateKey) {
      setClosedUpdateKey(currentUpdateKey);
    }
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

  const handleNonAdminDismiss = () => {
    handleClose();
    if (typeof window !== "undefined") {
      try {
        sessionStorage.setItem(SESSION_DISMISSED_KEY, "true");
      } catch {
        // ignore
      }
    }
    setIsSessionDismissed(true);
  };

  const handleSkipClick = () => {
    setShowSkipConfirm(true);
  };

  const handleSkipConfirmOpenChange = (open: boolean) => {
    setShowSkipConfirm(open);
  };

  const handleSkipUpdateClick = () => {
    setShowSkipConfirm(false);
    if (!backupCustom) {
      setShowUpdateConfirm(true);
    } else {
      handleConfirmUpdate(true);
    }
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
        setClosedUpdateKey(null);
      } else {
        toast.success("Flows updated successfully");
        handleClose();
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to update flows";
      setErrorMessage(msg);
      toast.error(msg);
      setShowUpdateConfirm(false);
      setClosedUpdateKey(null);
    } finally {
      setIsUpdatingWithBackup(null);
    }
  };

  if (targetUpdates.length === 0) return null;
  if (overrideOpen === undefined && undismissedUpdates.length === 0)
    return null;
  if (!isAdmin && overrideOpen === undefined && isSessionDismissed) return null;

  if (!isAdmin) {
    return (
      <NonAdminUpdateDialog
        open={isMainOpen}
        onClose={handleClose}
        onDismiss={handleNonAdminDismiss}
      />
    );
  }

  const isBusy = updateMutation.isPending || dismissMutation.isPending;

  return (
    <>
      <AdminUpdateDialog
        open={isMainOpen}
        errorMessage={errorMessage}
        backupCustom={backupCustom}
        isOnboarding={isOnboarding}
        isUpdating={updateMutation.isPending}
        isBusy={isBusy}
        onClose={handleClose}
        onBackupCustomChange={setBackupCustom}
        onSkip={handleSkipClick}
        onUpdate={handleInitialUpdateClick}
      />
      <SkipUpdateConfirmDialog
        open={showSkipConfirm}
        isBusy={isBusy}
        isDismissing={dismissMutation.isPending}
        onOpenChange={handleSkipConfirmOpenChange}
        onUpdate={handleSkipUpdateClick}
        onDismiss={handleDismiss}
      />
      <UpdateWithoutBackupDialog
        open={showUpdateConfirm}
        isUpdating={updateMutation.isPending}
        isUpdatingWithBackup={isUpdatingWithBackup}
        onOpenChange={setShowUpdateConfirm}
        onBackupAndUpdate={() => {
          setBackupCustom(true);
          handleConfirmUpdate(true);
        }}
        onContinueWithoutBackup={() => handleConfirmUpdate(false)}
      />
    </>
  );
}
