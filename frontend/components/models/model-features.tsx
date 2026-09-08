"use client";

import { useId, useState } from "react";
import AiFoundryLogo from "@/components/icons/ai-foundry-logo";
import AnthropicLogo from "@/components/icons/anthropic-logo";
import AzureOpenAILogo from "@/components/icons/azure-openai-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";
import { CAPABILITY_ICONS } from "./capability-icons";
import type { CatalogModel } from "./catalog-models";
import {
  ALL_CAPABILITIES,
  formatPrice,
  formatTokens,
  supports,
} from "./model-info";

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-background px-4 py-3">
      <div className="text-[10px] uppercase tracking-[0.5px] text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 text-mmd tabular-nums">{value}</div>
    </div>
  );
}

const PROVIDER_LOGOS: Record<
  string,
  React.ComponentType<{ className?: string }>
> = {
  openai: OpenAILogo,
  anthropic: AnthropicLogo,
  watsonx: IBMLogo,
  ollama: OllamaLogo,
  // Both Azure rows: `azure_ai` is Foundry, `azure` is Azure OpenAI Service,
  // and Microsoft draws the two differently.
  azure_ai: AiFoundryLogo,
  azure: AzureOpenAILogo,
};

function ProviderMark({ provider, name }: { provider?: string; name: string }) {
  const Logo = provider ? PROVIDER_LOGOS[provider] : undefined;
  return (
    <span
      aria-hidden="true"
      data-provider={provider}
      className="grid size-9 shrink-0 place-items-center rounded-[4px] bg-muted/60"
    >
      {Logo ? (
        <Logo className="size-5 text-foreground" />
      ) : (
        <span className="font-mono text-xs font-semibold tracking-wide text-muted-foreground">
          {(provider || name).slice(0, 2).toUpperCase()}
        </span>
      )}
    </span>
  );
}

export function ModelFeatures({
  model,
  providerName,
  provider,
}: {
  model: CatalogModel;
  providerName: string;
  provider?: string;
}) {
  const [showDetails, setShowDetails] = useState(false);
  const detailsId = useId();
  const supportedCapabilities = ALL_CAPABILITIES.filter(({ key }) =>
    supports(model, key),
  );

  const facts = [
    ["Provider", providerName],
    ["Context", formatTokens(model.max_input_tokens)],
    ["Max output", formatTokens(model.max_output_tokens)],
    [
      "Input",
      model.input_cost_per_token == null
        ? "—"
        : `${formatPrice(model.input_cost_per_token)} /M`,
    ],
    [
      "Output",
      model.output_cost_per_token == null
        ? "—"
        : `${formatPrice(model.output_cost_per_token)} /M`,
    ],
  ];
  if (model.cache_read_input_token_cost != null) {
    facts.push([
      "Cached input",
      `${formatPrice(model.cache_read_input_token_cost)} /M`,
    ]);
  }

  return (
    <div className="divide-y divide-border border border-border">
      {/* Header row — provider mark, model name, and the details toggle.
          Always visible; mirrors the compact Figma design. */}
      <div className="flex items-center gap-3 bg-muted/40 px-4 py-3">
        <ProviderMark provider={provider} name={providerName} />
        <p className="min-w-0 flex-1 truncate font-medium leading-tight">
          {model.model}
        </p>
        <button
          type="button"
          onClick={() => setShowDetails((open) => !open)}
          aria-expanded={showDetails}
          aria-controls={detailsId}
          className="shrink-0 text-mmd text-primary hover:underline"
        >
          {showDetails ? "Hide details" : "View details"}
        </button>
      </div>
      {showDetails && (
        <div id={detailsId} className="bg-background">
          <div className="grid grid-cols-2 gap-px bg-border">
            {facts.map(([label, value]) => (
              <Fact key={label} label={label} value={value} />
            ))}
            {/* Odd fact count leaves one grid cell empty; without a filler
                it shows the grid's own bg-border instead of a cell background. */}
            {facts.length % 2 === 1 && (
              <div aria-hidden="true" className="bg-background px-4 py-3" />
            )}
          </div>
          <div className="space-y-2 px-4 py-3 empty:hidden">
            {model.mode !== "embedding" &&
              !supports(model, "function_calling") && (
                <p className="border-l-2 border-destructive pl-2 text-mmd text-muted-foreground">
                  This model does not advertise function calling, so it may not
                  be able to run the OpenRAG agent tools.
                </p>
              )}
            {model.deprecation_date && (
              <p className="border-l-2 border-warning pl-2 text-mmd text-muted-foreground">
                Retires {model.deprecation_date}.
              </p>
            )}
          </div>
        </div>
      )}
      {/* Capability chips — only the capabilities this model supports, as in
          the design. Omit the row entirely rather than show an empty box. */}
      {supportedCapabilities.length > 0 && (
        <ul className="flex flex-wrap gap-2 px-4 py-3">
          {supportedCapabilities.map(({ key, label, hint }) => {
            const Icon = CAPABILITY_ICONS[key];
            return (
              <li
                key={key}
                title={hint}
                className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-1 text-xs text-foreground"
              >
                <Icon className="size-3" />
                {label}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
