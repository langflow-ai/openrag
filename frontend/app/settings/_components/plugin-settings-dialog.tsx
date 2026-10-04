"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import type { Connector } from "@/app/api/queries/useGetConnectorsQuery";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface Defaults {
  connection_id?: string | null;
  config?: Record<string, unknown>;
  secrets_set?: Record<string, boolean>;
  config_fields?: Connector["configFields"];
  status?: string;
  error?: string;
}

async function request(url: string, options?: RequestInit): Promise<Defaults> {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      data.error || data.detail || `Request failed (${response.status})`,
    );
  return data;
}

export default function PluginSettingsDialog({
  connector,
  setOpen,
}: {
  connector: Connector;
  setOpen: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const {
    data: defaults,
    isLoading,
    error: defaultsError,
    refetch,
  } = useQuery({
    queryKey: ["plugin-defaults", connector.type],
    queryFn: () =>
      request(
        `/api/connectors/${encodeURIComponent(connector.type)}/plugin-defaults`,
      ),
    retry: false,
  });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState(false);
  const fields = (
    connector.configFields ??
    defaults?.config_fields ??
    []
  ).filter(
    (field) =>
      field &&
      /^[a-zA-Z][a-zA-Z0-9_]*$/.test(field.name) &&
      (field.type === "text" || field.type === "secret"),
  );
  const connectionId = defaults?.connection_id;
  const config = Object.fromEntries(
    fields.map((field) => {
      const stored = defaults?.config?.[field.name];
      const value =
        draft[field.name] ??
        (field.type === "text" && typeof stored === "string" ? stored : "");
      return [field.name, value];
    }),
  );

  async function submit(mode: "test" | "save") {
    setError(null);
    const missing = fields.find(
      (field) =>
        field.required &&
        !config[field.name] &&
        !(
          field.type === "secret" &&
          connectionId &&
          defaults?.secrets_set?.[field.name]
        ),
    );
    if (missing) {
      setError(`${missing.label} is required`);
      return;
    }
    const pairedSecrets =
      fields.some(
        (field) => field.name === "username" && field.type === "secret",
      ) &&
      fields.some(
        (field) => field.name === "password" && field.type === "secret",
      );
    if (
      pairedSecrets &&
      Boolean(config.username) !== Boolean(config.password)
    ) {
      setError("Enter both Username and Password to change these credentials.");
      return;
    }
    setBusy(mode);
    try {
      const result = await request(
        `/api/connectors/${encodeURIComponent(connector.type)}/${mode === "test" ? "plugin-test" : "plugin-configure"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            config: Object.fromEntries(
              Object.entries(config).filter(
                ([name, value]) =>
                  value ||
                  !fields.some(
                    (field) => field.name === name && field.type === "secret",
                  ),
              ),
            ),
            ...(connectionId ? { connection_id: connectionId } : {}),
          }),
        },
      );
      if (mode === "test") {
        if (result.status && result.status !== "ok")
          throw new Error("Connection test failed");
        setTested(true);
        toast.success(
          "Connection test succeeded. Settings have not been saved.",
        );
      } else {
        await queryClient.invalidateQueries({ queryKey: ["connectors"] });
        await queryClient.invalidateQueries({
          queryKey: ["plugin-defaults", connector.type],
        });
        toast.success(`${connector.name} configured`);
        setOpen(false);
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Connection request failed",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog open onOpenChange={setOpen}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Configure {connector.name}</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <p role="status">Loading settings…</p>
        ) : defaultsError ? (
          <div role="alert">
            <p>
              {defaultsError instanceof Error
                ? defaultsError.message
                : "Could not load settings"}
            </p>
            <Button type="button" variant="outline" onClick={() => refetch()}>
              Retry
            </Button>
          </div>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit("save");
            }}
            className="space-y-4"
          >
            {fields.map((field) => (
              <div key={field.name} className="space-y-2">
                <Label htmlFor={`plugin-${field.name}`}>{field.label}</Label>
                {field.name === "site_paths" && field.type === "text" ? (
                  <Textarea
                    id={`plugin-${field.name}`}
                    rows={4}
                    required={field.required}
                    value={config[field.name]}
                    onChange={(event) => {
                      setDraft((current) => ({
                        ...current,
                        [field.name]: event.target.value,
                      }));
                      setTested(false);
                    }}
                  />
                ) : (
                  <Input
                    id={`plugin-${field.name}`}
                    type={field.type === "secret" ? "password" : "text"}
                    autoComplete="off"
                    required={
                      field.required &&
                      !(
                        field.type === "secret" &&
                        connectionId &&
                        defaults?.secrets_set?.[field.name]
                      )
                    }
                    value={config[field.name]}
                    onChange={(event) => {
                      setDraft((current) => ({
                        ...current,
                        [field.name]: event.target.value,
                      }));
                      setTested(false);
                    }}
                  />
                )}
                {field.type === "secret" &&
                  Boolean(defaults?.secrets_set?.[field.name]) && (
                    <p className="text-xs text-muted-foreground">
                      Saved secret available. Leave blank to keep it.
                    </p>
                  )}
              </div>
            ))}
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            {tested && (
              <p role="status" className="text-sm">
                Connection tested; save to persist these settings.
              </p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => void submit("test")}
                disabled={busy !== null}
              >
                Test connection
              </Button>
              <Button type="submit" disabled={busy !== null}>
                {busy === "save" ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
