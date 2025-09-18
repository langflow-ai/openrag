import { LabelInput } from "@/components/label-input";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { AdvancedOnboarding } from "./advanced";

export function OpenAIOnboarding({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: (settings: Settings) => void;
}) {
  return (
    <>
      <LabelInput
        label="OpenAI API key"
        helperText="The API key for your OpenAI account."
        id="api-key"
        required
        placeholder="sk-..."
      />
      <AdvancedOnboarding modelProvider="openai" />
    </>
  );
}
