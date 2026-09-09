import { cn } from "@/lib/utils";
import { CAPABILITY_ICONS } from "./capability-icons";
import type { CatalogModel } from "./catalog-models";
import { formatContext, PRIMARY_CAPABILITIES, supports } from "./model-info";

export function CapabilityStrip({ model }: { model: CatalogModel }) {
  return (
    // A visual summary inside a listbox option: the option is named after its
    // model, and the full capability breakdown is announced by `ModelFeatures`
    // once a model is selected. Announcing each icon here would only bury the
    // model name in the option's label.
    <span aria-hidden="true" className="ml-auto flex items-center gap-1">
      {PRIMARY_CAPABILITIES.map(({ key, label }) => {
        const Icon = CAPABILITY_ICONS[key];
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
      {/* Fixed-width so the capability icons line up across option rows,
          regardless of the context string ("8K" vs "1M" vs empty). */}
      <span className="ml-1 w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {formatContext(model.max_input_tokens)}
      </span>
    </span>
  );
}
