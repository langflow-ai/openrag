import type { ToolCallResult } from "@/app/chat/_types/types";

export interface CitedSource {
  item: ToolCallResult;
  index: number;
}

const addPrimaryLookupKey = (
  sourceLookup: Map<string, ToolCallResult>,
  key: string | undefined,
  source: ToolCallResult,
) => {
  if (key) sourceLookup.set(key, source);
};

const addFallbackLookupKey = (
  sourceLookup: Map<string, ToolCallResult | null>,
  key: string | undefined,
  source: ToolCallResult,
) => {
  if (!key) return;

  if (sourceLookup.has(key)) {
    sourceLookup.set(key, null);
    return;
  }

  sourceLookup.set(key, source);
};

/**
 * Derives a display filename from citation data.
 * Extracts the filename from a file path or uses the filename field directly.
 */
export const deriveDisplayFilename = (
  filePath: string | undefined,
  filename: string | undefined,
  fallback: string = "Document",
): string => {
  const path = filePath || filename || fallback;
  return path.split("/").pop() || path;
};

const buildSourceLookup = (sources: ToolCallResult[]) => {
  const primaryLookup = new Map<string, ToolCallResult>();
  const fallbackLookup = new Map<string, ToolCallResult | null>();

  for (const source of sources) {
    addPrimaryLookupKey(primaryLookup, source.chunk_id, source);
    addPrimaryLookupKey(primaryLookup, source.id, source);
    addFallbackLookupKey(fallbackLookup, source.data?.file_path, source);
    addFallbackLookupKey(fallbackLookup, source.filename, source);
  }

  return {
    get(id: string): ToolCallResult | undefined {
      const primarySource = primaryLookup.get(id);
      if (primarySource) return primarySource;

      const fallbackSource = fallbackLookup.get(id);
      return fallbackSource ?? undefined;
    },
  };
};

export const preprocessCitations = (
  text: string,
  sources: ToolCallResult[] | undefined,
): { text: string; citedSources: CitedSource[] } => {
  if (!sources || sources.length === 0) {
    return { text, citedSources: [] };
  }

  const sourceLookup = buildSourceLookup(sources);
  const citedSourcesMap = new Map<string, number>();
  const citedSourcesList: CitedSource[] = [];
  let nextIndex = 1;

  // Patterns: (Source: chunk_id) or [Source: chunk_id]
  const regex = /\[Source:\s*([^\]]+)\]|\(Source:\s*([^)]+)\)/g;

  const processedText = text.replace(regex, (_match, p1, p2) => {
    const rawIds = p1 || p2;
    if (!rawIds) return "";

    const ids = rawIds.split(",").map((id: string) => id.trim());
    const replacementBadges: string[] = [];

    for (const rawId of ids) {
      const foundSource = sourceLookup.get(rawId);

      if (foundSource) {
        const uniqueKey = (foundSource.chunk_id ||
          foundSource.id ||
          foundSource.filename ||
          JSON.stringify(foundSource)) as string;

        let index = citedSourcesMap.get(uniqueKey);
        if (index === undefined) {
          index = nextIndex++;
          citedSourcesMap.set(uniqueKey, index);
          citedSourcesList.push({ item: foundSource, index });
        }
        replacementBadges.push(`[\\[${index}\\]](#citation-${index})`);
      }
    }

    if (replacementBadges.length > 0) {
      return replacementBadges.join("");
    }

    return "";
  });

  return { text: processedText, citedSources: citedSourcesList };
};
