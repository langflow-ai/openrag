"use client";

import {
  Braces,
  Brain,
  Cpu,
  Database,
  Eye,
  FileText,
  Globe,
  ListChecks,
  type LucideIcon,
  Mic,
  Wrench,
} from "lucide-react";
import type { CatalogModel } from "@/app/settings/_helpers/catalog-models";
import {
  ALL_CAPABILITIES,
  formatContext,
  formatPrice,
  formatTokens,
  type ModelCapability,
  PRIMARY_CAPABILITIES,
  supports,
} from "@/app/settings/_helpers/model-info";
import AnthropicLogo from "@/components/icons/anthropic-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";
import { cn } from "@/lib/utils";

const ICONS: Record<ModelCapability, LucideIcon> = {
  function_calling: Wrench,
  vision: Eye,
  reasoning: Brain,
  structured_output: Braces,
  prompt_caching: Database,
  pdf_input: FileText,
  web_search: Globe,
  audio_input: Mic,
  computer_use: Cpu,
  parallel_tools: ListChecks,
};

export function CapabilityStrip({ model }: { model: CatalogModel }) {
  return (
    // A visual summary inside a listbox option: the option is named after its
    // model, and the full capability breakdown is announced by `ModelFeatures`
    // once a model is selected. Announcing each icon here would only bury the
    // model name in the option's label.
    <span aria-hidden="true" className="ml-auto flex items-center gap-1">
      {PRIMARY_CAPABILITIES.map(({ key, label }) => {
        const Icon = ICONS[key];
        const enabled = supports(model, key);
        return (
          <span
            key={key}
            title={`${label}: ${enabled ? "supported" : "unsupported"}`}
            className="inline-flex"
          >
            <Icon
              className={cn(
                "h-3.5 w-3.5",
                enabled ? "text-primary" : "text-muted-foreground/35",
              )}
            />
          </span>
        );
      })}
      {formatContext(model.max_input_tokens) && (
        <span className="ml-1 text-xs text-muted-foreground">
          {formatContext(model.max_input_tokens)}
        </span>
      )}
    </span>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-muted/40 p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
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
};

function ProviderMark({ provider, name }: { provider?: string; name: string }) {
  const Logo = provider ? PROVIDER_LOGOS[provider] : undefined;
  return (
    <span
      aria-hidden="true"
      data-provider={provider}
      className="grid h-16 w-16 shrink-0 place-items-center border border-border bg-white"
    >
      {Logo ? (
        <Logo className="h-10 w-10 text-black" />
      ) : (
        <span className="font-mono text-lg font-semibold tracking-wide text-muted-foreground">
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
    <div className="space-y-3 border border-border p-3">
      <div className="flex items-center gap-3">
        <ProviderMark provider={provider} name={providerName} />
        <div className="min-w-0">
          <p className="truncate font-medium leading-tight">{model.model}</p>
          <p className="truncate text-mmd text-muted-foreground">
            {providerName}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-px bg-border">
        {facts.map(([label, value]) => (
          <Fact key={label} label={label} value={value} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-1.5">
        {ALL_CAPABILITIES.map(({ key, label, hint }) => {
          const Icon = ICONS[key];
          const enabled = supports(model, key);
          return (
            <li
              key={key}
              title={hint}
              className={cn(
                "inline-flex items-center gap-1 border px-1.5 py-0.5 text-xs",
                enabled
                  ? "border-primary/40 text-foreground"
                  : "border-border text-muted-foreground/50",
              )}
            >
              <Icon className="h-3 w-3" />
              {label}
            </li>
          );
        })}
      </ul>
      {model.mode !== "embedding" && !supports(model, "function_calling") && (
        <p className="border-l-2 border-destructive pl-2 text-mmd text-muted-foreground">
          This model does not advertise function calling, so it may not be able
          to run the BomaRAG agent tools.
        </p>
      )}
      {model.deprecation_date && (
        <p className="border-l-2 border-warning pl-2 text-mmd text-muted-foreground">
          Retires {model.deprecation_date}.
        </p>
      )}
    </div>
  );
}
