import { apiClient } from "@/lib/api-client";
import type { KnowledgeFilter } from "./useGetFiltersSearchQuery";

export async function getFilterById(
  filterId: string,
): Promise<KnowledgeFilter | null> {
  try {
    const response = await apiClient.get<{
      success?: boolean;
      filter?: KnowledgeFilter;
    }>(`/knowledge-filter/${filterId}`);
    const json = response.data;
    if (response.status < 200 || response.status >= 300 || !json.success) {
      return null;
    }
    return json.filter as KnowledgeFilter;
  } catch (error) {
    console.error("Failed to fetch filter by ID:", error);
    return null;
  }
}

/**
 * The saved filter document, falling back to the chat's in-memory copy.
 *
 * An open chat keeps the filter as it was when it was picked. Editing that
 * filter on the Knowledge page does not update the copy, so a send has to
 * read the document again.
 */
export async function latestSavedFilter(
  current: KnowledgeFilter | null,
): Promise<KnowledgeFilter | null> {
  if (!current?.id) return current;
  const fresh = await getFilterById(current.id);
  return fresh ?? current;
}
