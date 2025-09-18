import { LabelInput } from "@/components/label-input";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { AdvancedOnboarding } from "./advanced";

export function IBMOnboarding({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: (settings: Settings) => void;
}) {
  return (
    <>
      <LabelInput
        label="watsonx.ai API Endpoint"
        helperText="The API endpoint for your watsonx.ai account."
        id="api-endpoint"
        required
        placeholder="https://..."
      />
      <LabelInput
        label="IBM API key"
        helperText="The API key for your watsonx.ai account."
        id="api-key"
        required
        placeholder="sk-..."
      />
      <LabelInput
        label="IBM Project ID"
        helperText="The project ID for your watsonx.ai account."
        id="project-id"
        required
        placeholder="..."
      />
      <AdvancedOnboarding modelProvider="watsonx" />
    </>
  );
}
