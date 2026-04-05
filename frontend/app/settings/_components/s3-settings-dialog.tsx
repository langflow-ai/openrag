"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import { useS3ConfigureMutation } from "@/app/api/mutations/useS3ConfigureMutation";
import { useS3DefaultsQuery } from "@/app/api/queries/useS3DefaultsQuery";
import AwsLogo from "@/components/icons/aws-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { type S3FormData, S3SettingsForm } from "./s3-settings-form";

interface S3SettingsDialogProps {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export default function S3SettingsDialog({
  open,
  setOpen,
}: S3SettingsDialogProps) {
  const queryClient = useQueryClient();

  const { data: defaults } = useS3DefaultsQuery({ enabled: open });

  const methods = useForm<S3FormData>({
    mode: "onSubmit",
    values: {
      access_key: "",
      secret_key: "",
      session_token: "",
      endpoint_url: defaults?.endpoint ?? "",
      region: defaults?.region ?? "",
      bucket_names_input: defaults?.bucket_names?.join(", ") ?? "",
    },
  });

  const { handleSubmit } = methods;

  const [buckets, setBuckets] = useState<string[] | null>(
    defaults?.bucket_names?.length ? defaults.bucket_names : null,
  );
  const [selectedBuckets, setSelectedBuckets] = useState<string[]>(
    defaults?.bucket_names ?? [],
  );

  // Sync bucket state when defaults load asynchronously after dialog mount
  useEffect(() => {
    if (defaults?.bucket_names?.length) {
      setBuckets(defaults.bucket_names);
      setSelectedBuckets((prev) =>
        prev.length ? prev : defaults.bucket_names,
      );
    }
  }, [defaults?.bucket_names?.join(",")]);

  const [isFetchingBuckets, setIsFetchingBuckets] = useState(false);
  const [bucketsError, setBucketsError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const configureMutation = useS3ConfigureMutation();

  const parseBucketNames = (value: string) =>
    value
      .split(",")
      .map((bucket) => bucket.trim())
      .filter(Boolean);

  const getErrorMessage = (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback;

  const handleTestConnection = handleSubmit(async (data) => {
    setIsFetchingBuckets(true);
    setBucketsError(null);
    setFormError(null);
    const parsedBucketNames = parseBucketNames(data.bucket_names_input);

    try {
      const result = await configureMutation.mutateAsync({
        access_key: data.access_key || undefined,
        secret_key: data.secret_key || undefined,
        session_token: data.session_token || undefined,
        endpoint_url: data.endpoint_url || undefined,
        region: data.region || undefined,
        bucket_names:
          parsedBucketNames.length > 0
            ? parsedBucketNames
            : selectedBuckets.length > 0
              ? selectedBuckets
              : undefined,
        connection_id: defaults?.connection_id ?? undefined,
      });

      const res = await fetch(
        `/api/connectors/aws_s3/${result.connection_id}/buckets`,
      );
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || "Failed to list buckets");

      const fetchedBuckets: string[] = json.buckets;
      setBuckets(fetchedBuckets);

      setSelectedBuckets((prev) =>
        parsedBucketNames.length > 0
          ? fetchedBuckets
          : prev.filter((b) => fetchedBuckets.includes(b)),
      );

      queryClient.invalidateQueries({ queryKey: ["s3-defaults"] });
    } catch (error: unknown) {
      setBucketsError(getErrorMessage(error, "Connection failed"));
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
      const parsedBucketNames = parseBucketNames(data.bucket_names_input);
      const latestDefaults = await queryClient.fetchQuery({
        queryKey: ["s3-defaults"],
        queryFn: async () => {
          const res = await fetch("/api/connectors/aws_s3/defaults");
          return res.json();
        },
        staleTime: 0,
      });

      await configureMutation.mutateAsync({
        access_key: data.access_key || undefined,
        secret_key: data.secret_key || undefined,
        session_token: data.session_token || undefined,
        endpoint_url: data.endpoint_url || undefined,
        region: data.region || undefined,
        bucket_names:
          selectedBuckets.length > 0 ? selectedBuckets : parsedBucketNames,
        connection_id:
          latestDefaults?.connection_id ?? defaults?.connection_id ?? undefined,
      });

      toast.success("Amazon S3 configured", {
        description:
          selectedBuckets.length > 0
            ? `Will ingest from: ${selectedBuckets.join(", ")}`
            : "Will auto-discover and ingest all accessible buckets.",
        icon: <AwsLogo className="w-4 h-4" />,
      });

      queryClient.invalidateQueries({ queryKey: ["connectors"] });
      setOpen(false);
    } catch (error: unknown) {
      setFormError(getErrorMessage(error, "Failed to save configuration"));
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
                  <AwsLogo className="text-black" />
                </div>
                Amazon S3 Setup
              </DialogTitle>
            </DialogHeader>

            <S3SettingsForm
              buckets={buckets}
              selectedBuckets={selectedBuckets}
              onSelectedBucketsChange={setSelectedBuckets}
              isFetchingBuckets={isFetchingBuckets}
              bucketsError={bucketsError}
              onTestConnection={handleTestConnection as () => void}
              accessKeySet={defaults?.access_key_set}
              secretKeySet={defaults?.secret_key_set}
              sessionTokenSet={defaults?.session_token_set}
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
