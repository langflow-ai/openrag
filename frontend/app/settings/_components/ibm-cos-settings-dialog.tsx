"use client";

import { useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import IBMCOSIcon from "@/components/icons/ibm-cos-icon";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { IBMCOSSettingsForm, type IBMCOSFormData } from "./ibm-cos-settings-form";
import { useIBMCOSDefaultsQuery } from "@/app/api/queries/useIBMCOSDefaultsQuery";
import { useIBMCOSConfigureMutation } from "@/app/api/mutations/useIBMCOSConfigureMutation";

interface IBMCOSSettingsDialogProps {
    open: boolean;
    setOpen: (open: boolean) => void;
}

export default function IBMCOSSettingsDialog({
    open,
    setOpen,
}: IBMCOSSettingsDialogProps) {
    const queryClient = useQueryClient();

    // Fetch env-based defaults to pre-fill the form
    const { data: defaults } = useIBMCOSDefaultsQuery({ enabled: open });

    const disableIam = defaults?.disable_iam ?? false;

    const methods = useForm<IBMCOSFormData>({
        mode: "onSubmit",
        values: {
            auth_mode: disableIam ? "hmac" : (defaults?.auth_mode ?? "hmac"),
            endpoint: defaults?.endpoint ?? "",
            api_key: "",
            service_instance_id: defaults?.service_instance_id ?? "",
            hmac_access_key: "",
            hmac_secret_key: "",
        },
    });

    const { handleSubmit } = methods;

    // Bucket state
    const [buckets, setBuckets] = useState<string[] | null>(
        defaults?.bucket_names?.length ? defaults.bucket_names : null,
    );
    const [selectedBuckets, setSelectedBuckets] = useState<string[]>(
        defaults?.bucket_names ?? [],
    );
    const [isFetchingBuckets, setIsFetchingBuckets] = useState(false);
    const [bucketsError, setBucketsError] = useState<string | null>(null);
    const [formError, setFormError] = useState<string | null>(null);

    const configureMutation = useIBMCOSConfigureMutation();

    // Inline bucket test: calls the configure endpoint without saving,
    // then uses the returned connection_id to list buckets.
    const handleTestConnection = handleSubmit(async (data) => {
        setIsFetchingBuckets(true);
        setBucketsError(null);
        setFormError(null);

        try {
            // First configure (creates/updates connection) to get a connection_id
            const result = await configureMutation.mutateAsync({
                auth_mode: data.auth_mode,
                endpoint: data.endpoint,
                api_key: data.api_key || undefined,
                service_instance_id: data.service_instance_id || undefined,
                hmac_access_key: data.hmac_access_key || undefined,
                hmac_secret_key: data.hmac_secret_key || undefined,
                connection_id: defaults?.connection_id ?? undefined,
            });

            // Then list buckets using the connection
            const res = await fetch(
                `/api/connectors/ibm_cos/${result.connection_id}/buckets`,
            );
            const json = await res.json();
            if (!res.ok) throw new Error(json.error || "Failed to list buckets");

            const fetchedBuckets: string[] = json.buckets;
            setBuckets(fetchedBuckets);

            // Keep any previously selected buckets that still exist
            setSelectedBuckets((prev) =>
                prev.filter((b) => fetchedBuckets.includes(b)),
            );

            // Refresh defaults so we have the new connection_id
            queryClient.invalidateQueries({ queryKey: ["ibm-cos-defaults"] });
        } catch (err: any) {
            setBucketsError(err.message ?? "Connection failed");
        } finally {
            setIsFetchingBuckets(false);
        }
    });

    const onSubmit = handleSubmit(async (data) => {
        setFormError(null);
        if (buckets === null) {
            setFormError("Test the connection first to validate credentials.");
            return;
        }

        try {
            // Refresh defaults to get latest connection_id
            const latestDefaults = await queryClient.fetchQuery({
                queryKey: ["ibm-cos-defaults"],
                queryFn: async () => {
                    const res = await fetch("/api/connectors/ibm_cos/defaults");
                    return res.json();
                },
                staleTime: 0,
            });

            await configureMutation.mutateAsync({
                auth_mode: data.auth_mode,
                endpoint: data.endpoint,
                api_key: data.api_key || undefined,
                service_instance_id: data.service_instance_id || undefined,
                hmac_access_key: data.hmac_access_key || undefined,
                hmac_secret_key: data.hmac_secret_key || undefined,
                bucket_names: selectedBuckets,
                connection_id: latestDefaults?.connection_id ?? defaults?.connection_id ?? undefined,
            });

            toast.success("IBM Cloud Object Storage configured", {
                description:
                    selectedBuckets.length > 0
                        ? `Will ingest from: ${selectedBuckets.join(", ")}`
                        : "Will auto-discover and ingest all accessible buckets.",
                icon: <IBMCOSIcon className="w-4 h-4" />,
            });

            queryClient.invalidateQueries({ queryKey: ["connectors"] });
            setOpen(false);
        } catch (err: any) {
            setFormError(err.message ?? "Failed to save configuration");
        }
    });

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent autoFocus={false} className="max-w-2xl max-h-[90vh] overflow-y-auto">
                <FormProvider {...methods}>
                    <form onSubmit={onSubmit} className="grid gap-4">
                        <DialogHeader className="mb-2">
                            <DialogTitle className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                                    <IBMCOSIcon className="text-black" />
                                </div>
                                IBM Cloud Object Storage Setup
                            </DialogTitle>
                        </DialogHeader>

                        <IBMCOSSettingsForm
                            buckets={buckets}
                            selectedBuckets={selectedBuckets}
                            onSelectedBucketsChange={setSelectedBuckets}
                            isFetchingBuckets={isFetchingBuckets}
                            bucketsError={bucketsError}
                            onTestConnection={handleTestConnection as () => void}
                            apiKeySet={defaults?.api_key_set}
                            hmacAccessKeySet={defaults?.hmac_access_key_set}
                            hmacSecretKeySet={defaults?.hmac_secret_key_set}
                            formError={formError}
                            disableIam={disableIam}
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
                                disabled={configureMutation.isPending || isFetchingBuckets}
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
