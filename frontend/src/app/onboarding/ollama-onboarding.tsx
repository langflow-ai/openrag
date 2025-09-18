import { LabelInput } from "@/components/label-input";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { AdvancedOnboarding } from "./advanced";

export function OllamaOnboarding({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: (settings: Settings) => void;
}) {
  return (
    <>
      <LabelInput
        label="Ollama Endpoint"
        helperText="The endpoint for your Ollama server."
        id="api-endpoint"
        required
        placeholder="http://..."
      />

      <AdvancedOnboarding modelProvider="ollama" />
    </>
  );
}
