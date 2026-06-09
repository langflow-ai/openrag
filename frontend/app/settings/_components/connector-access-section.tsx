"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  useGetConnectorAccessQuery,
  useUpdateConnectorAccessMutation,
} from "@/app/api/queries/useGetConnectorsQuery";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

export function ConnectorAccessSection() {
  const {
    data: connectors = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useGetConnectorAccessQuery();
  const updateAccess = useUpdateConnectorAccessMutation();
  /** Non-null only after the user edits; server data stays the source of truth until then. */
  const [userDraft, setUserDraft] = useState<Record<string, boolean> | null>(
    null,
  );

  const serverSnapshot = useMemo(
    () => connectors.map((c) => `${c.type}:${c.enabled}`).join("|"),
    [connectors],
  );

  // Reset draft when server data catches up; keep unsaved edits on refetch/focus.
  useEffect(() => {
    setUserDraft((draft) => {
      if (!draft) return null;
      const hasUnsavedEdits = connectors.some(
        (c) => draft[c.type] !== c.enabled,
      );
      return hasUnsavedEdits ? draft : null;
    });
  }, [serverSnapshot, connectors]);

  const accessForSave = useMemo(
    () =>
      Object.fromEntries(
        connectors.map((c) => [c.type, userDraft?.[c.type] ?? c.enabled]),
      ),
    [connectors, userDraft],
  );

  const isDirty = useMemo(() => {
    if (!userDraft) return false;
    return connectors.some((c) => userDraft[c.type] !== c.enabled);
  }, [connectors, userDraft]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg ibm-settings-section-title">
          Connectors Permission
        </CardTitle>
        <CardDescription className="text-sm">
          Control which connectors are available in this workspace for everyone,
          including admins.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </div>
        ) : isError ? (
          <div className="space-y-3 text-sm">
            <p className="text-destructive">
              {error instanceof Error
                ? error.message
                : "Failed to load connectors permission"}
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => refetch()}
            >
              Retry
            </Button>
          </div>
        ) : (
          <>
            <ul className="space-y-4">
              {connectors.map((connector) => {
                const enabled =
                  userDraft?.[connector.type] ?? connector.enabled;

                return (
                  <li
                    key={connector.type}
                    className="flex items-center justify-between gap-4 rounded-lg bg-muted/20 px-5 py-4"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{connector.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {enabled
                          ? "Available in this workspace"
                          : "Disabled for this workspace"}
                      </p>
                    </div>
                    <Switch
                      checked={enabled}
                      disabled={updateAccess.isPending}
                      aria-label={`${enabled ? "Disable" : "Enable"} ${connector.name} for this workspace`}
                      onCheckedChange={(checked) => {
                        setUserDraft((prev) => {
                          const base =
                            prev ??
                            Object.fromEntries(
                              connectors.map((c) => [c.type, c.enabled]),
                            );
                          return { ...base, [connector.type]: checked };
                        });
                      }}
                    />
                  </li>
                );
              })}
            </ul>
            <div className="flex justify-end pt-6">
              <Button
                onClick={() =>
                  updateAccess.mutate(accessForSave, {
                    onSuccess: () => setUserDraft(null),
                  })
                }
                disabled={updateAccess.isPending || !isDirty}
                className="min-w-[120px]"
                size="sm"
                variant="outline"
              >
                {updateAccess.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving…
                  </>
                ) : (
                  "Save changes"
                )}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
