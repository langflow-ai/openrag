"use client";

import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

/** Preset retention options, each expressed as a number of days.
 *  The operator cap (conversation_ttl_days) may reduce the available choices.
 *  Maximum enforced by the backend is 90 days. */
const RETENTION_PRESETS: { label: string; days: number }[] = [
  { label: "7 days", days: 7 },
  { label: "14 days", days: 14 },
  { label: "30 days", days: 30 },
  { label: "60 days", days: 60 },
  { label: "90 days", days: 90 },
];

export function ConversationSettingsSection() {
  const { data: settings = {} } = useGetSettingsQuery();
  const updateSettings = useUpdateSettingsMutation({
    onSuccess: () => toast.success("Settings updated successfully"),
    onError: (error) =>
      toast.error("Failed to update settings", { description: error.message }),
  });

  const operatorCap = settings.conversation_ttl_days; // null → disabled globally
  const globallyDisabled = operatorCap == null;
  const pruningEnabled =
    !globallyDisabled && settings.conversation_pruning_enabled !== false;

  // Effective retention shown in the selector (falls back to operator cap).
  const effectiveDays =
    settings.conversation_retention_days ?? operatorCap ?? 90;

  // Only show presets that don't exceed the operator cap.
  const availablePresets = RETENTION_PRESETS.filter(
    (p) => operatorCap == null || p.days <= operatorCap,
  );

  // If the current effectiveDays isn't one of the standard presets, add it as
  // a read-only option so the select renders the correct value.
  const hasExactPreset = availablePresets.some((p) => p.days === effectiveDays);
  const displayPresets =
    !hasExactPreset && !globallyDisabled
      ? [
          ...availablePresets,
          { label: `${effectiveDays} days`, days: effectiveDays },
        ].sort((a, b) => a.days - b.days)
      : availablePresets;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Conversation history</CardTitle>
        <CardDescription>
          Control automatic cleanup of stale conversation metadata.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Toggle row */}
        <div className="flex items-center justify-between gap-4">
          <label
            htmlFor="conversation-pruning"
            className="text-sm font-medium cursor-pointer"
          >
            Automatically delete inactive conversations
          </label>
          {updateSettings.isPending &&
          updateSettings.variables &&
          "conversation_pruning_enabled" in updateSettings.variables ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-label="Saving" />
          ) : (
            <Switch
              id="conversation-pruning"
              checked={pruningEnabled}
              disabled={globallyDisabled}
              onCheckedChange={(checked) =>
                updateSettings.mutate({ conversation_pruning_enabled: checked })
              }
            />
          )}
        </div>

        {/* Retention period sentence */}
        {globallyDisabled ? (
          <p className="text-sm text-muted-foreground">
            Disabled by the deployment administrator.
          </p>
        ) : (
          <p className="text-sm text-muted-foreground flex flex-wrap items-center gap-1">
            Conversations with no activity for{" "}
            {updateSettings.isPending &&
            updateSettings.variables &&
            "conversation_retention_days" in updateSettings.variables ? (
              <Loader2
                className="h-4 w-4 animate-spin inline"
                aria-label="Saving"
              />
            ) : (
              <Select
                value={String(effectiveDays)}
                disabled={!pruningEnabled}
                onValueChange={(value) =>
                  updateSettings.mutate({
                    conversation_retention_days: Number(value),
                  })
                }
              >
                <SelectTrigger
                  className="h-6 w-auto min-w-[90px] px-2 py-0 text-sm inline-flex"
                  aria-label="Retention period"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {displayPresets.map((preset) => (
                    <SelectItem key={preset.days} value={String(preset.days)}>
                      {preset.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}{" "}
            are permanently deleted, including their messages and attachments.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
