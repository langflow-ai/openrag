"use client";

import { useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface S3FormData {
    access_key: string;
    secret_key: string;
    endpoint_url: string;
    region: string;
}

interface S3SettingsFormProps {
    /** Available buckets after a successful test — null means not yet tested */
    buckets: string[] | null;
    selectedBuckets: string[];
    onSelectedBucketsChange: (buckets: string[]) => void;
    isFetchingBuckets: boolean;
    bucketsError: string | null;
    onTestConnection: () => void;
    accessKeySet?: boolean;
    secretKeySet?: boolean;
    formError?: string | null;
}

export function S3SettingsForm({
    buckets,
    selectedBuckets,
    onSelectedBucketsChange,
    isFetchingBuckets,
    bucketsError,
    onTestConnection,
    accessKeySet,
    secretKeySet,
    formError,
}: S3SettingsFormProps) {
    const { register } = useFormContext<S3FormData>();

    const toggleBucket = (name: string, checked: boolean) => {
        if (checked) {
            onSelectedBucketsChange([...selectedBuckets, name]);
        } else {
            onSelectedBucketsChange(selectedBuckets.filter((b) => b !== name));
        }
    };

    const toggleAll = (checked: boolean) => {
        onSelectedBucketsChange(checked ? (buckets ?? []) : []);
    };

    return (
        <div className="space-y-5">
            {/* Access Key ID */}
            <div className="space-y-1">
                <LabelWrapper
                    label="Access Key ID"
                    helperText="From AWS IAM → Users → Security credentials. Or set the AWS_ACCESS_KEY_ID env var."
                    id="s3-access-key"
                    required
                >
                    <Input
                        {...register("access_key", { setValueAs: (v) => v?.trim() })}
                        id="s3-access-key"
                        type="password"
                        placeholder={
                            accessKeySet
                                ? "•••••••• (loaded from env)"
                                : "AKIAIOSFODNN7EXAMPLE"
                        }
                        autoComplete="off"
                    />
                </LabelWrapper>
            </div>

            {/* Secret Access Key */}
            <div className="space-y-1">
                <LabelWrapper
                    label="Secret Access Key"
                    helperText="Or set the AWS_SECRET_ACCESS_KEY env var."
                    id="s3-secret-key"
                    required
                >
                    <Input
                        {...register("secret_key", { setValueAs: (v) => v?.trim() })}
                        id="s3-secret-key"
                        type="password"
                        placeholder={
                            secretKeySet
                                ? "•••••••• (loaded from env)"
                                : "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                        }
                        autoComplete="off"
                    />
                </LabelWrapper>
            </div>

            {/* Endpoint URL (optional) */}
            <div className="space-y-1">
                <LabelWrapper
                    label="Endpoint URL"
                    helperText="Leave blank for AWS S3. For MinIO, Cloudflare R2, or other S3-compatible services, enter the endpoint URL. Or set the AWS_S3_ENDPOINT env var."
                    id="s3-endpoint"
                >
                    <Input
                        {...register("endpoint_url", { setValueAs: (v) => v?.trim() })}
                        id="s3-endpoint"
                        placeholder="https://your-minio.example.com"
                        autoComplete="off"
                    />
                </LabelWrapper>
            </div>

            {/* Region (optional) */}
            <div className="space-y-1">
                <LabelWrapper
                    label="Region"
                    helperText="AWS region (e.g. us-east-1, eu-west-1). Default: us-east-1. Or set the AWS_REGION env var."
                    id="s3-region"
                >
                    <Input
                        {...register("region", { setValueAs: (v) => v?.trim() })}
                        id="s3-region"
                        placeholder="us-east-1"
                        autoComplete="off"
                    />
                </LabelWrapper>
            </div>

            {/* Test connection */}
            <Button
                type="button"
                variant="outline"
                onClick={onTestConnection}
                disabled={isFetchingBuckets}
                className="w-full"
            >
                {isFetchingBuckets ? (
                    <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Connecting…
                    </>
                ) : buckets !== null ? (
                    <>
                        <RefreshCcw className="h-4 w-4 mr-2" />
                        Refresh Buckets
                    </>
                ) : (
                    "Test Connection & List Buckets"
                )}
            </Button>

            {bucketsError && (
                <p className="text-sm text-destructive rounded-lg border border-destructive/50 p-3">
                    {bucketsError}
                </p>
            )}

            {formError && (
                <p className="text-sm text-destructive rounded-lg border border-destructive/50 p-3">
                    {formError}
                </p>
            )}

            {/* Bucket selector */}
            {buckets !== null && (
                <div className="space-y-2">
                    <div className="flex items-center justify-between">
                        <Label className="text-sm font-medium">
                            Select Buckets to Ingest
                            <span className="ml-1 text-muted-foreground font-normal">
                                (leave all unchecked to ingest everything)
                            </span>
                        </Label>
                        {buckets.length > 1 && (
                            <button
                                type="button"
                                className="text-xs text-primary underline-offset-2 hover:underline"
                                onClick={() =>
                                    toggleAll(selectedBuckets.length !== buckets.length)
                                }
                            >
                                {selectedBuckets.length === buckets.length
                                    ? "Deselect all"
                                    : "Select all"}
                            </button>
                        )}
                    </div>

                    {buckets.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                            No buckets found for this account.
                        </p>
                    ) : (
                        <div className="max-h-48 overflow-y-auto rounded-lg border p-3 space-y-2">
                            {buckets.map((bucket) => (
                                <label
                                    key={bucket}
                                    htmlFor={`s3-bucket-${bucket}`}
                                    className="flex items-center gap-2.5 cursor-pointer select-none"
                                >
                                    <input
                                        id={`s3-bucket-${bucket}`}
                                        type="checkbox"
                                        className="h-4 w-4 rounded border-border accent-primary"
                                        checked={selectedBuckets.includes(bucket)}
                                        onChange={(e) =>
                                            toggleBucket(bucket, e.target.checked)
                                        }
                                    />
                                    <span className="text-sm">{bucket}</span>
                                </label>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
