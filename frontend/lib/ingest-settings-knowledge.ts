import type { KnowledgeSettings } from "@/app/api/queries/useGetSettingsQuery";
import type { IngestSettings } from "@/components/cloud-picker/types";
import { DEFAULT_KNOWLEDGE_SETTINGS } from "@/lib/constants";

/** Map saved Knowledge settings to ingest panel fields (subset of Knowledge UI). */
export function knowledgeToIngestSettings(
  knowledge: KnowledgeSettings | null | undefined,
): IngestSettings {
  return {
    chunkSize: knowledge?.chunk_size ?? DEFAULT_KNOWLEDGE_SETTINGS.chunk_size,
    chunkOverlap:
      knowledge?.chunk_overlap ?? DEFAULT_KNOWLEDGE_SETTINGS.chunk_overlap,
    ocr: knowledge?.ocr ?? DEFAULT_KNOWLEDGE_SETTINGS.ocr,
    pictureDescriptions:
      knowledge?.picture_descriptions ??
      DEFAULT_KNOWLEDGE_SETTINGS.picture_descriptions,
    embeddingModel:
      knowledge?.embedding_model?.trim() || "text-embedding-3-small",
  };
}
