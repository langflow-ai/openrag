import { toast } from "sonner";
import { SUGGEST_MAX_CHARS } from "@/app/api/queries/useGetSearchSuggestions";

/**
 * Clamp typed or pasted search text to the suggestion length cap and tell the
 * user when input was dropped. The fixed toast id keeps held keys from stacking
 * popups.
 */
export function limitSearchInput(value: string): string {
  const characters = [...value];
  if (characters.length <= SUGGEST_MAX_CHARS) return value;
  toast.error(`Search is limited to ${SUGGEST_MAX_CHARS} characters.`, {
    id: "search-query-limit",
  });
  return characters.slice(0, SUGGEST_MAX_CHARS).join("");
}
