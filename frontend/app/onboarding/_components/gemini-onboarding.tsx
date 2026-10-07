import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import GoogleLogo from "@/components/icons/google-logo";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import { providerCatalogOptions } from "@/components/models/catalog-models";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { AdvancedOnboarding } from "./advanced";

export function GeminiOnboarding({
  setSettings,
  isEmbedding = false,
  hasEnvApiKey = false,
}: {
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  isEmbedding?: boolean;
  hasEnvApiKey?: boolean;
}) {
  const [apiKey, setApiKey] = useState("");
  const [getFromEnv, setGetFromEnv] = useState(hasEnvApiKey);
  const debouncedApiKey = useDebouncedValue(apiKey, 500);

  const { data: catalog } = useGetModelCatalogQuery();

  const models = useMemo(
    () =>
      providerCatalogOptions(
        catalog,
        "gemini",
        isEmbedding ? "embedding" : "language",
      ),
    [catalog, isEmbedding],
  );

  const [model, setModel] = useState("");

  // Auto-default to the first catalogue model, same as GenericOnboarding does.
  const defaultedRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (model || models.length === 0) return;
    const first = models[0].value;
    if (defaultedRef.current === first) return;
    defaultedRef.current = first;
    setModel(first);
  }, [models, model]);

  // Stable ref so the sync effect does not re-run on every render.
  const setSettingsRef = useRef(setSettings);
  setSettingsRef.current = setSettings;

  // Sync credentials + model into the shared onboarding state whenever any
  // relevant value changes.
  useEffect(() => {
    const effectiveKey = getFromEnv ? "" : debouncedApiKey;
    setSettingsRef.current((prev) => ({
      ...prev,
      ...(isEmbedding
        ? { embedding_provider: "gemini", embedding_model: model }
        : { llm_provider: "gemini", llm_model: model }),
      provider_credentials: effectiveKey
        ? { ...prev.provider_credentials, gemini: { api_key: effectiveKey } }
        : getFromEnv
          ? { ...prev.provider_credentials, gemini: {} }
          : prev.provider_credentials,
    }));
  }, [getFromEnv, debouncedApiKey, model, isEmbedding]);

  const handleGetFromEnvChange = (fromEnv: boolean) => {
    setGetFromEnv(fromEnv);
    if (fromEnv) {
      setApiKey("");
    }
    setModel("");
  };

  return (
    <>
      <div className="space-y-5">
        <LabelWrapper
          label="Use environment Gemini API key"
          id="gemini-get-api-key"
          description="Reuse the key from your environment config. Turn off to enter a different key."
          flex
        >
          <Tooltip>
            <TooltipTrigger asChild>
              <div>
                <Switch
                  checked={getFromEnv}
                  data-testid="gemini-get-from-env-switch"
                  onCheckedChange={handleGetFromEnvChange}
                  disabled={!hasEnvApiKey}
                />
              </div>
            </TooltipTrigger>
            {!hasEnvApiKey && (
              <TooltipContent>
                Gemini API key not detected in the environment.
              </TooltipContent>
            )}
          </Tooltip>
        </LabelWrapper>
        {!getFromEnv && (
          <LabelInput
            label="Gemini API key"
            helperText="The API key for your Google AI Studio / Gemini account."
            id="gemini-api-key"
            type="password"
            required
            placeholder="AIza..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        )}
      </div>
      <AdvancedOnboarding
        icon={<GoogleLogo className="w-4 h-4" />}
        languageModels={isEmbedding ? undefined : models}
        embeddingModels={isEmbedding ? models : undefined}
        languageModel={isEmbedding ? undefined : model}
        embeddingModel={isEmbedding ? model : undefined}
        setLanguageModel={isEmbedding ? undefined : setModel}
        setEmbeddingModel={isEmbedding ? setModel : undefined}
      />
    </>
  );
}
