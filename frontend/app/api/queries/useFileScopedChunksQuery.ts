import {
  EMPTY_SEARCH_RESULT,
  type File,
  type SearchResult,
  useGetSearchQuery,
} from "@/app/api/queries/useGetSearchQuery";
import { fileScopedSearchQueryData } from "@/lib/file-chunks";

/** Loads every chunk for one filename (shared by chunks page + FileChunksPanel). */
export function useFileScopedChunksQuery(filename: string | null | undefined) {
  const queryData = filename ? fileScopedSearchQueryData(filename) : null;
  const { data = EMPTY_SEARCH_RESULT, isFetching } = useGetSearchQuery(
    "*",
    queryData,
    { enabled: Boolean(filename) },
  );
  const file = (data as SearchResult).files.find(
    (entry: File) => entry.filename === filename,
  );
  return { file, isFetching };
}
