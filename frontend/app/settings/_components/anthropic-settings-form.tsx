/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import { useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";

export interface AnthropicSettingsFormData {
  apiKey: string;
}

export function AnthropicSettingsForm({
  modelsError,
  isLoadingModels,
}: {
  modelsError?: Error | null;
  isLoadingModels?: boolean;
}) {
  const {
    register,
    formState: { errors },
  } = useFormContext<AnthropicSettingsFormData>();

  const apiKeyError = modelsError
    ? "Invalid Anthropic API key. Verify or replace the key."
    : errors.apiKey?.message;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <LabelWrapper
          label="Anthropic API key"
          helperText="The API key for your Anthropic account"
          required
          id="api-key"
        >
          <Input
            {...register("apiKey", {
              required: "API key is required",
            })}
            className={apiKeyError ? "!border-destructive" : ""}
            id="api-key"
            type="password"
            autoComplete="new-password"
            placeholder="sk-ant-..."
          />
        </LabelWrapper>
        {apiKeyError && (
          <p className="text-sm text-destructive">{apiKeyError}</p>
        )}
        {isLoadingModels && (
          <p className="text-sm text-muted-foreground">Validating API key...</p>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Configure language models in the Settings page after saving your API
        key. Note: Anthropic does not provide embedding models.
      </p>
    </div>
  );
}
