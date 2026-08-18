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
import Image from "next/image";
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
import {
  providerLogo,
  providerMonogram,
} from "@/app/settings/_helpers/provider-logos";
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
    <span className="ml-auto flex items-center gap-1">
      {PRIMARY_CAPABILITIES.map(({ key, label }) => {
        const Icon = ICONS[key];
        const enabled = supports(model, key);
        return (
          <Icon
            key={key}
            aria-label={`${label}: ${enabled ? "supported" : "unsupported"}`}
            className={cn(
              "h-3.5 w-3.5",
              enabled ? "text-primary" : "text-muted-foreground/35",
            )}
          />
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

function ProviderMark({ provider, name }: { provider?: string; name: string }) {
  const src = provider ? providerLogo(provider) : null;
  return (
    <span
      aria-hidden="true"
      data-provider={provider}
      className="grid h-16 w-16 shrink-0 place-items-center border border-border bg-white"
    >
      {src ? (
        <Image
          src={src}
          alt=""
          width={44}
          height={44}
          className="object-contain"
        />
      ) : (
        <span className="font-mono text-lg font-semibold tracking-wide text-muted-foreground">
          {providerMonogram(provider || name)}
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
          to run the OpenRAG agent tools.
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
