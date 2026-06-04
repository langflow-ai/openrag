"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useUpdateConnectorAccessMutation } from "@/app/api/mutations/useUpdateConnectorAccessMutation";
import { useGetConnectorAccessQuery } from "@/app/api/queries/useGetConnectorAccessQuery";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";

export function ConnectorAccessSection() {
  const isCloudBrand = useIsCloudBrand();
  const { roles } = useAuth();

  if (!isCloudBrand || !roles.includes("admin")) {
    return null;
  }

  return <ConnectorAccessForm />;
}

function ConnectorAccessForm() {
  const {
    data: connectors = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useGetConnectorAccessQuery();
  const updateAccess = useUpdateConnectorAccessMutation();
  const [draft, setDraft] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (connectors.length > 0) {
      setDraft(Object.fromEntries(connectors.map((c) => [c.type, c.enabled])));
    }
  }, [connectors]);

  const isDirty = useMemo(() => {
    return connectors.some((c) => draft[c.type] !== c.enabled);
  }, [connectors, draft]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg ibm-settings-section-title">
          Connector access
        </CardTitle>
        <CardDescription className="text-sm">
          Choose which connectors other users in this workspace can connect and
          use. You always have access to all connectors.
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
                : "Failed to load connector access"}
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
                const enabled = draft[connector.type] ?? connector.enabled;

                return (
                  <li
                    key={connector.type}
                    className="flex items-center justify-between gap-4 rounded-lg bg-muted/20 px-5 py-4"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{connector.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {enabled
                          ? "Available to all users"
                          : "Hidden from other users"}
                      </p>
                    </div>
                    <Switch
                      checked={enabled}
                      disabled={updateAccess.isPending}
                      aria-label={`${enabled ? "Disable" : "Enable"} ${connector.name} for users`}
                      onCheckedChange={(checked) => {
                        setDraft((prev) => ({
                          ...prev,
                          [connector.type]: checked,
                        }));
                      }}
                    />
                  </li>
                );
              })}
            </ul>
            <div className="flex justify-end pt-6">
              <Button
                onClick={() => updateAccess.mutate(draft)}
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
