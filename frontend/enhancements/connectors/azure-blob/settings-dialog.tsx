"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
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
  const [isFetchingContainers, setIsFetchingContainers] = useState(false);
  const [containersError, setContainersError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const configureMutation = useAzureBlobConfigureMutation();

  const handleTestConnection = handleSubmit(async (data) => {
    setIsFetchingContainers(true);
    setContainersError(null);
    setFormError(null);

    try {
      const result = await configureMutation.mutateAsync({
        auth_mode: data.auth_mode,
        connection_string: data.connection_string || undefined,
        account_name: data.account_name || undefined,
        account_key: data.account_key || undefined,
        endpoint: data.endpoint || undefined,
        connection_id: defaults?.connection_id ?? undefined,
      });

      const res = await fetch(
        `/api/connectors/azure_blob/${result.connection_id}/containers`,
      );
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || "Failed to list containers");

      const fetched: string[] = json.containers;
      setContainers(fetched);
      setSelectedContainers((prev) => prev.filter((c) => fetched.includes(c)));

      queryClient.invalidateQueries({ queryKey: ["azure-blob-defaults"] });
    } catch (err: any) {
      setContainersError(err.message ?? "Connection failed");
    } finally {
      setIsFetchingContainers(false);
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
            ? `Will ingest from: ${selectedContainers.join(", ")}`
            : "Will auto-discover and ingest all accessible containers.",
        icon: <AzureBlobIcon className="w-4 h-4" />,
      });

      queryClient.invalidateQueries({ queryKey: ["connectors"] });
      setOpen(false);
    } catch (err: any) {
      setFormError(err.message ?? "Failed to save configuration");
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
