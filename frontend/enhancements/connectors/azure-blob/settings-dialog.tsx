"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import AzureBlobIcon from "./icon";
import { type AzureBlobFormData, AzureBlobSettingsForm } from "./settings-form";
import { useAzureBlobConfigureMutation } from "./useAzureBlobConfigureMutation";
import { useAzureBlobDefaultsQuery } from "./useAzureBlobDefaultsQuery";

interface AzureBlobSettingsDialogProps {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export default function AzureBlobSettingsDialog({
  open,
  setOpen,
}: AzureBlobSettingsDialogProps) {
  const queryClient = useQueryClient();

  const { data: defaults } = useAzureBlobDefaultsQuery({ enabled: open });

  const methods = useForm<AzureBlobFormData>({
    mode: "onSubmit",
    values: {
      auth_mode: defaults?.auth_mode ?? "connection_string",
      connection_string: "",
      account_name: defaults?.account_name ?? "",
      account_key: "",
      endpoint: defaults?.endpoint ?? "",
    },
  });

  const { handleSubmit } = methods;

  const [containers, setContainers] = useState<string[] | null>(
    defaults?.container_names?.length ? defaults.container_names : null,
  );
  const [selectedContainers, setSelectedContainers] = useState<string[]>(
    defaults?.container_names ?? [],
  );
  useEffect(() => {
    if (defaults?.container_names?.length) {
      setContainers(defaults.container_names);
      setSelectedContainers(defaults.container_names);
    }
  }, [defaults]);

  const [isFetchingContainers, setIsFetchingContainers] = useState(false);
  const [containersError, setContainersError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const configureMutation = useAzureBlobConfigureMutation();

  // Holds the AbortController for the currently in-flight test request so it
  // can be cancelled if the user closes the dialog or starts a new test.
  const testAbortRef = useRef<AbortController | null>(null);

  // Abort any in-flight test request when the component unmounts (i.e. when
  // the dialog is closed, since connector-cards renders it only while open).
  useEffect(() => {
    return () => {
      testAbortRef.current?.abort();
    };
  }, []);

  const handleTestConnection = handleSubmit(async (data) => {
    // Cancel any previous in-flight test before starting a new one.
    testAbortRef.current?.abort();
    const controller = new AbortController();
    testAbortRef.current = controller;

    setIsFetchingContainers(true);
    setContainersError(null);
    setFormError(null);

    try {
      // Validate credentials + list containers WITHOUT persisting. Saving is
      // reserved for the Save button (onSubmit), so testing never creates or
      // mutates the connection or clobbers the stored container selection.
      const res = await fetch("/api/connectors/azure_blob/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          auth_mode: data.auth_mode,
          connection_string: data.connection_string || undefined,
          account_name: data.account_name || undefined,
          account_key: data.account_key || undefined,
          endpoint: data.endpoint || undefined,
          connection_id: defaults?.connection_id ?? undefined,
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || "Failed to list containers");

      const fetched: string[] = json.containers;
      setContainers(fetched);
      setSelectedContainers((prev) => prev.filter((c) => fetched.includes(c)));
    } catch (err: unknown) {
      // Ignore cancellations — they are intentional (dialog closed or new test
      // started) and must not surface an error message to the user.
      if (err instanceof DOMException && err.name === "AbortError") return;
      setContainersError(
        err instanceof Error ? err.message : "Connection failed",
      );
    } finally {
      // Only clear the loading flag if this invocation is still the active one.
      // If the user started a second test while this one was in flight, the
      // second call already replaced testAbortRef.current; clearing here would
      // flicker the spinner off for the still-running request.
      if (testAbortRef.current === controller) {
        setIsFetchingContainers(false);
      }
    }
  });

  const onSubmit = handleSubmit(async (data) => {
    setFormError(null);
    if (containers === null) {
      setFormError("Test the connection first to validate credentials.");
      return;
    }

    try {
      const latestDefaults = await queryClient.fetchQuery({
        queryKey: ["azure-blob-defaults"],
        queryFn: async () => {
          const res = await fetch("/api/connectors/azure_blob/defaults");
          return res.json();
        },
        staleTime: 0,
      });

      await configureMutation.mutateAsync({
        auth_mode: data.auth_mode,
        connection_string: data.connection_string || undefined,
        account_name: data.account_name || undefined,
        account_key: data.account_key || undefined,
        endpoint: data.endpoint || undefined,
        container_names: selectedContainers,
        connection_id:
          latestDefaults?.connection_id ?? defaults?.connection_id ?? undefined,
      });

      toast.success("Azure Blob Storage configured", {
        description:
          selectedContainers.length > 0
            ? `Ingestion restricted to the following containers: ${selectedContainers.join(", ")}.`
            : "All accessible containers available for ingestion.",
        icon: <AzureBlobIcon className="w-4 h-4" />,
      });

      queryClient.invalidateQueries({ queryKey: ["connectors"] });
      setOpen(false);
    } catch (err: unknown) {
      setFormError(
        err instanceof Error ? err.message : "Failed to save configuration",
      );
    }
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        autoFocus={false}
        className="max-w-2xl max-h-[90vh] overflow-y-auto"
      >
        <FormProvider {...methods}>
          <form onSubmit={onSubmit} className="grid gap-4">
            <DialogHeader className="mb-2">
              <DialogTitle className="flex items-center gap-3">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                  <AzureBlobIcon />
                </div>
                Azure Blob Storage Setup
              </DialogTitle>
            </DialogHeader>

            <AzureBlobSettingsForm
              containers={containers}
              selectedContainers={selectedContainers}
              onSelectedContainersChange={setSelectedContainers}
              isFetchingContainers={isFetchingContainers}
              containersError={containersError}
              onTestConnection={handleTestConnection as () => void}
              connectionStringSet={defaults?.connection_string_set}
              accountKeySet={defaults?.account_key_set}
              formError={formError}
            />

            <DialogFooter className="mt-4">
              <Button
                variant="outline"
                type="button"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={configureMutation.isPending || isFetchingContainers}
              >
                {configureMutation.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
}
