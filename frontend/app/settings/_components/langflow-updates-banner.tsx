"use client";

import { AlertCircle, FileDown } from "lucide-react";
import { useState } from "react";
import { useUpdateFlowsMutation } from "@/app/api/mutations/useUpdateFlowsMutation";
import { useGetFlowsUpdatesQuery } from "@/app/api/queries/useGetFlowsUpdatesQuery";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export function LangflowUpdatesBanner() {
  const { data: updates, isLoading } = useGetFlowsUpdatesQuery();
  const updateMutation = useUpdateFlowsMutation();
  const [isUpdating, setIsUpdating] = useState(false);

  if (isLoading || !updates || updates.length === 0) return null;

  const hasCustomFlows = updates.some((u) => u.is_custom);

  const handleUpdate = async () => {
    setIsUpdating(true);
    const flowTypes = updates.map((u) => u.flow_type);

    try {
      const results = await updateMutation.mutateAsync({
        flow_types: flowTypes,
        backup_custom: true, // Always backup from settings banner
      });

      // Download backups if any
      results.forEach((res) => {
        if (res.success && res.backup_content && res.backup_path) {
          const filename = res.backup_path.split("/").pop() || "backup.json";
          const blob = new Blob([res.backup_content], {
            type: "application/json",
          });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }
      });
    } catch (e) {
      console.error("Failed to update flows", e);
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <div className="mb-6">
      <Alert
        variant="warning"
        className="border-amber-500/50 bg-amber-500/10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
      >
        <div className="flex gap-3">
          <AlertCircle className="h-5 w-5 text-amber-600 dark:text-amber-500 mt-0.5" />
          <div>
            <AlertTitle className="text-amber-800 dark:text-amber-400 text-base">
              Langflow Flow Updates Available
            </AlertTitle>
            <AlertDescription className="text-amber-700 dark:text-amber-300 mt-1">
              There are newer versions of the Langflow flows available.
              {hasCustomFlows &&
                " Note: You have custom modifications. Updating will overwrite them, but a backup will be downloaded automatically."}
            </AlertDescription>
            <ul className="list-disc pl-4 mt-2 text-sm text-amber-700 dark:text-amber-300">
              {updates.map((update) => (
                <li key={update.flow_type}>
                  {update.flow_type}
                  {update.is_custom && " (Custom)"}
                </li>
              ))}
            </ul>
          </div>
        </div>
        <Button
          onClick={handleUpdate}
          disabled={isUpdating}
          variant="outline"
          className="shrink-0 bg-white dark:bg-black border-amber-500/30 hover:bg-amber-50 dark:hover:bg-amber-900/20"
        >
          {isUpdating ? "Updating..." : "Update Flows"}
          {!isUpdating && hasCustomFlows && (
            <FileDown className="ml-2 h-4 w-4" />
          )}
        </Button>
      </Alert>
    </div>
  );
}
