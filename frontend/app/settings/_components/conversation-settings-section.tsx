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
import { Switch } from "@/components/ui/switch";

export function ConversationSettingsSection() {
  const { data: settings = {} } = useGetSettingsQuery();
  const updateSettings = useUpdateSettingsMutation({
    onSuccess: () => toast.success("Settings updated successfully"),
    onError: (error) =>
      toast.error("Failed to update settings", { description: error.message }),
  });

  const ttlDays = settings.conversation_ttl_days;
  const globallyDisabled = ttlDays == null;
  const enabled =
    !globallyDisabled && settings.conversation_pruning_enabled !== false;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Conversation history</CardTitle>
        <CardDescription>
          Control automatic cleanup of stale conversation metadata.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between gap-4">
          <div>
            <label
              htmlFor="conversation-pruning"
              className="text-sm font-medium cursor-pointer"
            >
              Automatically delete stale conversations
            </label>
            <p className="text-sm text-muted-foreground">
              {globallyDisabled
                ? "Disabled by the deployment administrator."
                : `Conversations inactive for more than ${ttlDays} days are deleted nightly.`}
            </p>
          </div>
          {updateSettings.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-label="Saving" />
          ) : (
            <Switch
              id="conversation-pruning"
              checked={enabled}
              disabled={globallyDisabled}
              onCheckedChange={(checked) =>
                updateSettings.mutate({
                  conversation_pruning_enabled: checked,
                })
              }
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
}
