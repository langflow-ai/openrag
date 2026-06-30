/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import type { KnowledgeFilter } from "./useGetFiltersSearchQuery";

export async function getFilterById(
  filterId: string,
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
