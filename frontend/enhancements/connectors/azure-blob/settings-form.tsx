"use client";

import { Loader2, RefreshCcw } from "lucide-react";
import { Controller, useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface AzureBlobFormData {
  auth_mode: "connection_string" | "account_key";
  // connection_string mode
  connection_string: string;
  // account_key mode
  account_name: string;
  account_key: string;
  endpoint: string;
}

interface AzureBlobSettingsFormProps {
  /** Available containers after a successful test — null means not yet tested */
  containers: string[] | null;
  selectedContainers: string[];
  onSelectedContainersChange: (containers: string[]) => void;
  isFetchingContainers: boolean;
  containersError: string | null;
  onTestConnection: () => void;
  connectionStringSet?: boolean;
  accountKeySet?: boolean;
  formError?: string | null;
  showContainers?: boolean;
  onAuthModeChange?: () => void;
}

export function AzureBlobSettingsForm({
  containers,
  selectedContainers,
  onSelectedContainersChange,
  isFetchingContainers,
  containersError,
  onTestConnection,
  connectionStringSet,
  accountKeySet,
  formError,
  showContainers,
  onAuthModeChange,
}: AzureBlobSettingsFormProps) {
  const {
    register,
    control,
    formState: { errors },
  } = useFormContext<AzureBlobFormData>();

  const toggleContainer = (name: string, checked: boolean) => {
    if (checked) {
      onSelectedContainersChange([...selectedContainers, name]);
    } else {
      onSelectedContainersChange(selectedContainers.filter((c) => c !== name));
    }
  };

  const toggleAll = (checked: boolean) => {
    onSelectedContainersChange(checked ? (containers ?? []) : []);
  };

  return (
    <div className="space-y-5">
      {/* Auth mode selector using Tabs */}
      <div className="space-y-2">
        <Label className="text-sm font-medium">Authentication Method</Label>
        <Controller
          control={control}
          name="auth_mode"
          render={({ field }) => (
            <Tabs
              value={field.value}
              onValueChange={(v) => {
                field.onChange(v);
                onAuthModeChange?.();
              }}
            >
              <TabsList className="w-full">
                <TabsTrigger value="connection_string">
                  <span className="font-semibold text-sm">
                    Connection String
                  </span>
                  <span className="text-xs text-muted-foreground font-normal">
                    Single paste-in string
                  </span>
                </TabsTrigger>
                <TabsTrigger value="account_key">
                  <span className="font-semibold text-sm">Account Key</span>
                  <span className="text-xs text-muted-foreground font-normal">
                    Account name + key
                  </span>
                </TabsTrigger>
              </TabsList>

              {/* Connection string fields — first tab */}
              <TabsContent value="connection_string">
                <div className="space-y-1">
                  <LabelWrapper
                    label="Connection String"
                    helperText="Azure Portal → Storage account → Access keys → Connection string. For the local Azurite emulator use: UseDevelopmentStorage=true"
                    id="azure-conn-str"
                    required
                  >
                    <Input
                      {...register("connection_string", {
                        setValueAs: (v) => v?.trim(),
                      })}
                      id="azure-conn-str"
                      type="password"
                      placeholder={
                        connectionStringSet
                          ? "•••••••• (loaded from env)"
                          : "DefaultEndpointsProtocol=https;AccountName=…"
                      }
                      autoComplete="off"
                    />
                  </LabelWrapper>
                </div>
              </TabsContent>

              {/* Account key fields — second tab */}
              <TabsContent value="account_key">
                <div className="space-y-4">
                  <div className="space-y-1">
                    <LabelWrapper
                      label="Account Name"
                      helperText="Your Azure Storage account name (e.g. mystorageacct). For Azurite use devstoreaccount1."
                      id="azure-account-name"
                      required
                    >
                      <Input
                        {...register("account_name", {
                          setValueAs: (v) => v?.trim(),
                        })}
                        id="azure-account-name"
                        placeholder="mystorageacct"
                        autoComplete="off"
                      />
                    </LabelWrapper>
                  </div>
                  <div className="space-y-1">
                    <LabelWrapper
                      label="Account Key"
                      helperText="Azure Portal → Storage account → Access keys → key1/key2"
                      id="azure-account-key"
                      required
                    >
                      <Input
                        {...register("account_key", {
                          setValueAs: (v) => v?.trim(),
                        })}
                        id="azure-account-key"
                        type="password"
                        placeholder={
                          accountKeySet
                            ? "•••••••• (loaded from env)"
                            : "base64 account key"
                        }
                        autoComplete="off"
                      />
                    </LabelWrapper>
                  </div>
                  <div className="space-y-1">
                    <LabelWrapper
                      label="Blob Endpoint (optional)"
                      helperText="Leave blank for public Azure. Set for Azurite (http://127.0.0.1:10000/devstoreaccount1) or sovereign clouds."
                      id="azure-endpoint"
                    >
                      <Input
                        {...register("endpoint", {
                          setValueAs: (v) => v?.trim(),
                        })}
                        id="azure-endpoint"
                        placeholder="https://mystorageacct.blob.core.windows.net"
                      />
                    </LabelWrapper>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          )}
        />
      </div>

      {/* Test connection */}
      <Button
        type="button"
        variant="outline"
        onClick={onTestConnection}
        disabled={isFetchingContainers}
        className="w-full"
      >
        {isFetchingContainers ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Connecting…
          </>
        ) : containers !== null ? (
          <>
            <RefreshCcw className="h-4 w-4 mr-2" />
            Refresh Containers
          </>
        ) : (
          "Test Connection & List Containers"
        )}
      </Button>

      {containersError && (
        <p className="text-sm text-destructive rounded-lg border border-destructive/50 p-3">
          {containersError}
        </p>
      )}

      {formError && (
        <p className="text-sm text-destructive rounded-lg border border-destructive/50 p-3">
          {formError}
        </p>
      )}

      {/* Container selector */}
      {containers !== null && showContainers && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">
              Restrict Ingestion to Containers
              <span className="ml-1 text-muted-foreground font-normal">
                (optional)
              </span>
            </Label>
            {containers.length > 1 && (
              <button
                type="button"
                className="text-xs text-primary underline-offset-2 hover:underline"
                onClick={() =>
                  toggleAll(selectedContainers.length !== containers.length)
                }
              >
                {selectedContainers.length === containers.length
                  ? "Deselect all"
                  : "Select all"}
              </button>
            )}
          </div>

          {containers.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No containers found for this account.
            </p>
          ) : (
            <div className="max-h-48 overflow-y-auto rounded-lg border p-3 space-y-2">
              {containers.map((container) => (
                <label
                  key={container}
                  htmlFor={`container-${container}`}
                  className="flex items-center gap-2.5 cursor-pointer select-none"
                >
                  <input
                    id={`container-${container}`}
                    type="checkbox"
                    className="h-4 w-4 rounded border-border accent-primary"
                    checked={selectedContainers.includes(container)}
                    onChange={(e) =>
                      toggleContainer(container, e.target.checked)
                    }
                  />
                  <span className="text-sm">{container}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Keep errors referenced so unused-var lint stays happy when fields hidden */}
      {errors.connection_string && (
        <p className="text-sm text-destructive">
          {errors.connection_string.message}
        </p>
      )}
    </div>
  );
}
