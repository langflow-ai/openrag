"use client";

import { AlertCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
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

export function FlowsUpdateDialog() {
  const { can } = usePermissions();
  const { data: updates, isLoading } = useGetFlowsUpdatesQuery();
  const updateMutation = useUpdateFlowsMutation();
  const [isOpen, setIsOpen] = useState(false);
  const hasDismissedRef = useRef(false);
  const [backupCustom, setBackupCustom] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    // Check sessionStorage on mount
    const dismissed =
      sessionStorage.getItem("openrag-flow-updates-shown") === "true";
    if (dismissed) {
      hasDismissedRef.current = true;
      return;
    }

    if (
      !isLoading &&
      updates &&
      updates.length > 0 &&
      !hasDismissedRef.current
    ) {
      setIsOpen(true);
    }
  }, [updates, isLoading]);

  const markDismissed = () => {
    setIsOpen(false);
    hasDismissedRef.current = true;
    sessionStorage.setItem("openrag-flow-updates-shown", "true");
  };

  const handleUpdate = async () => {
    if (!updates) return;
    setErrorMessage(null);
    const flowTypes = updates.map((u) => u.flow_type);

    try {
      const results = await updateMutation.mutateAsync({
        flow_types: flowTypes,
        backup_custom: backupCustom,
      });

      const failed = results.filter((r) => !r.success);
      if (failed.length > 0) {
        const errorText = failed
          .map((f) => `${f.flow_type}: ${f.error || "Update failed"}`)
          .join("; ");
        setErrorMessage(errorText);
        toast.error(`Flow update failed: ${errorText}`);
      } else {
        toast.success("Flows updated successfully");
        markDismissed();
      }
    } catch (e: any) {
      const msg = e?.message || "Failed to update flows";
      setErrorMessage(msg);
      toast.error(msg);
    }
  };

  const handleSkip = () => {
    markDismissed();
  };

  if (!can("flows:edit") || !updates || updates.length === 0) return null;

  const hasCustomFlows = updates.some((u) => u.is_custom);

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Flow Updates Available</DialogTitle>
          <DialogDescription>
            There are updates available for your Langflow flows. Updating
            ensures you have the latest features and bug fixes.
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
            {updates.map((update) => (
              <li key={update.flow_type}>
                <span className="font-medium">{update.flow_type}</span>
                {update.is_custom && (
                  <span className="ml-2 text-xs bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200 px-2 py-0.5 rounded-full">
                    Custom Modified
                  </span>
                )}
              </li>
            ))}
          </ul>

          {hasCustomFlows && (
            <Alert
              variant="default"
              className="border-yellow-500/50 bg-yellow-500/10"
            >
              <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-500" />
              <AlertTitle className="text-yellow-800 dark:text-yellow-400">
                Custom Flows Detected
              </AlertTitle>
              <AlertDescription className="text-yellow-700 dark:text-yellow-300">
                You have modified some of these flows. Updating will overwrite
                your custom changes, but backup flows will be created in
                Langflow so you can reference or redo your modifications.
              </AlertDescription>
            </Alert>
          )}

          {hasCustomFlows && (
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
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleSkip}>
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
