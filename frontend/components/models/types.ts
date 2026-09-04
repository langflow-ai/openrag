import type { ButtonProps } from "@/components/ui/button";
import type { CatalogModel } from "./catalog-models";

export type ModelOption = {
  value: string;
  label: string;
  default?: boolean;
  provider?: string;
  model?: CatalogModel;
  icon?: React.ReactNode;
};

export type GroupedModelOption = {
  group: string;
  /** Provider key for custom entries typed under this group. */
  provider?: string;
  options: ModelOption[];
  icon?: React.ReactNode;
};

export interface ModelSelectorProps extends ButtonProps {
  options?: ModelOption[];
  groupedOptions?: GroupedModelOption[];
  value: string;
  /** Disambiguates the same model id hosted by more than one vendor. */
  selectedProvider?: string;
  icon?: React.ReactNode;
  placeholder?: string;
  searchPlaceholder?: string;
  noOptionsPlaceholder?: string;
  custom?: boolean;
  onValueChange: (value: string, provider?: string) => void;
  hasError?: boolean;
  defaultOpen?: boolean;
}
