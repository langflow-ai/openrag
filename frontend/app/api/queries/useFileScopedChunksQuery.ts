import {
  EMPTY_SEARCH_RESULT,
  type File,
  type SearchResult,
  useGetSearchQuery,
} from "@/app/api/queries/useGetSearchQuery";
import { fileScopedSearchQueryData } from "@/lib/file-chunks";

/** Loads chunks for one filename, optionally scoped to a search query.
 *
 * When `searchQuery` is provided (non-wildcard), the search API is called with
 * that query filtered to the file — chunks come back with `highlights` set.
 * Without a query the wildcard path is used and highlights are empty.
 */
export function useFileScopedChunksQuery(
  filename: string | null | undefined,
  searchQuery?: string,
) {
  const effectiveQuery =
    searchQuery && searchQuery.trim() !== "*" && searchQuery.trim() !== ""
      ? searchQuery.trim()
      : "*";
  const queryData = filename ? fileScopedSearchQueryData(filename) : null;
  const { data = EMPTY_SEARCH_RESULT, isFetching } = useGetSearchQuery(
    effectiveQuery,
    queryData,
    { enabled: Boolean(filename) },
  );
  const file = (data as SearchResult).files.find(
    (entry: File) => entry.filename === filename,
  );
  return { file, isFetching };
}
