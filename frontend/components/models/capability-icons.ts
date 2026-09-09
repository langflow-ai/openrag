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
import type { ModelCapability } from "./model-info";

/**
 * Lucide glyph for each model capability, shared by `CapabilityStrip`
 * (the compact listbox summary) and `ModelFeatures` (the full breakdown).
 */
export const CAPABILITY_ICONS: Record<ModelCapability, LucideIcon> = {
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
