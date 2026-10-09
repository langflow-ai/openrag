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
