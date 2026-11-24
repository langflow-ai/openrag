"use client";

import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { RequirePermission } from "@/components/require-permission";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
import { useUpdateSettingsMutation } from "../../api/mutations/useUpdateSettingsMutation";

export function AdvancedSettingsSection() {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  const { data: settings, isLoading } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });
  const updateSettings = useUpdateSettingsMutation({
    onSuccess: () => toast.success("Advanced settings updated"),
    onError: (error) =>
      toast.error("Failed to update advanced settings", {
        description: error.message,
      }),
  });

  if (isLoading) {
    return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;
  }

  // DISABLE_LANGFLOW=true means there is no Langflow deployment to opt into,
  // so exposing an application-level choice would be misleading.
  // Older backends do not send this capability field. Treat an absent value as
  // configurable so a staggered frontend/backend deployment does not leave
  // the Advanced tab empty; only an explicit false hides the switch.
  if (settings?.langflow_configurable === false) return null;

  return (
    <RequirePermission perm="config:write">
      <section className="space-y-8" aria-labelledby="advanced-heading">
        <header>
          <div className="max-w-[685px] space-y-3">
            <h3
              id="advanced-heading"
              className={cn(
                "text-lg font-semibold leading-tight tracking-tight",
                isCloudBrand && "ibm-settings-section-title",
              )}
            >
              Advanced
            </h3>
            <p className="text-sm text-muted-foreground">
              Control deployment-wide behavior for the OpenRAG application.
            </p>
          </div>
        </header>
        <div className="w-full rounded-lg bg-muted/50 px-5">
          <div className="flex items-center justify-between gap-6 py-6">
            <div className="max-w-xl space-y-2 pl-3">
              <label
                htmlFor="disable-langflow"
                className="cursor-pointer text-base font-semibold"
              >
                Disable Langflow
              </label>
              <p className="text-sm text-muted-foreground">
                Use OpenRAG&apos;s native chat, ingestion, and suggested-prompt
                capabilities. Langflow editor and flow-management controls are
                hidden while this option is enabled.
              </p>
            </div>
            <Switch
              id="disable-langflow"
              aria-label="Disable Langflow"
              checked={settings?.langflow_enabled === false}
              disabled={updateSettings.isPending}
              onCheckedChange={(disable_langflow) =>
                updateSettings.mutate({ disable_langflow })
              }
            />
          </div>
        </div>
      </section>
    </RequirePermission>
  );
}
