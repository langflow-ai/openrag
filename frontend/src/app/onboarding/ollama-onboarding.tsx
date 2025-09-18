import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import OllamaLogo from "@/components/logo/ollama-logo";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { AdvancedOnboarding } from "./advanced";
import { ModelSelector } from "./model-selector";

export function OllamaOnboarding({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: (settings: Settings) => void;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const frameworks = [
    { value: "gpt-oss", label: "gpt-oss", default: true },
    { value: "llama3.1", label: "llama3.1" },
    { value: "llama3.2", label: "llama3.2" },
    { value: "llama3.3", label: "llama3.3" },
    { value: "llama3.4", label: "llama3.4" },
    { value: "llama3.5", label: "llama3.5" },
  ];
  return (
    <>
      <LabelInput
        label="Ollama Endpoint"
        helperText="The endpoint for your Ollama server."
        id="api-endpoint"
        required
        placeholder="http://..."
      />

      <LabelWrapper
        label="Embedding Model"
        helperText="The embedding model for your Ollama server."
        id="embedding-model"
        required={true}
      >
        <ModelSelector
          options={frameworks}
          icon={<OllamaLogo className="w-4 h-4" />}
          value={value}
          onValueChange={setValue}
        />
      </LabelWrapper>

      <AdvancedOnboarding modelProvider="ollama" />
    </>
  );
}
