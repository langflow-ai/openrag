"use client";

import { AlertCircle } from "lucide-react";
import { useEffect, useState } from "react";
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

export function FlowsUpdateDialog() {
  const { data: updates, isLoading } = useGetFlowsUpdatesQuery();
  const updateMutation = useUpdateFlowsMutation();
  const [isOpen, setIsOpen] = useState(false);
  const [hasDismissed, setHasDismissed] = useState(false);
  const [backupCustom, setBackupCustom] = useState(true);

  useEffect(() => {
    // Check sessionStorage on mount
    const dismissed =
      sessionStorage.getItem("openrag-flow-updates-shown") === "true";
    if (dismissed) {
      setHasDismissed(true);
      return;
    }

    if (!isLoading && updates && updates.length > 0 && !hasDismissed) {
      setIsOpen(true);
    }
  }, [updates, isLoading, hasDismissed]);

  const markDismissed = () => {
    setIsOpen(false);
    setHasDismissed(true);
    sessionStorage.setItem("openrag-flow-updates-shown", "true");
  };

  const handleUpdate = async () => {
    if (!updates) return;
    const flowTypes = updates.map((u) => u.flow_type);

    try {
      await updateMutation.mutateAsync({
        flow_types: flowTypes,
        backup_custom: backupCustom,
      });

      markDismissed();
    } catch (e) {
      console.error("Failed to update flows", e);
    }
  };

  const handleSkip = () => {
    markDismissed();
  };

  if (!updates || updates.length === 0) return null;

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
