import type { KnowledgeFilter } from "./useGetFiltersSearchQuery";

export async function getFilterById(
  filterId: string
): Promise<KnowledgeFilter | null> {
  try {
    const response = await fetch(`/api/knowledge-filter/${filterId}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    const json = await response.json();
    if (!response.ok || !json.success) {
      return null;
    }
    return json.filter as KnowledgeFilter;
  } catch (error) {
    console.error("Failed to fetch filter by ID:", error);
    return null;
  }
}
