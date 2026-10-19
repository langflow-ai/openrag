/**
 * One-line "why does this file match?" previews for search results.
 *
 * A `keyword` preview is an OpenSearch highlight fragment (matched terms wrapped
 * in `<mark>`), trimmed to one line with `…` where text was cut away. A
 * `semantic` preview is the sentence of the best chunk that shares the most
 * words with the query, shown when nothing matched literally.
 */
import type { ChunkResult, File } from "@/app/api/queries/useGetSearchQuery";
import { getKnowledgeFileIdentity } from "@/lib/knowledge-table-state";

export const PREVIEW_MAX_CHARS = 180;
/** How many of the most relevant files get a preview line in the table. */
export const TABLE_PREVIEW_FILE_COUNT = 3;

export interface SearchPreview {
  /** One line; `keyword` previews wrap matched terms in `<mark>`. */
  text: string;
  kind: "keyword" | "semantic";
}

const MARK_LENGTH = "<mark></mark>".length;
const MARK_SPLIT = /(<mark>.*?<\/mark>)/;

export function stripMarks(fragment: string): string {
  return fragment.replace(/<\/?mark>/g, "");
}

function isMarkPart(part: string): boolean {
  return part.startsWith("<mark>") && part.endsWith("</mark>");
}

/** Keep at most `limit` visible characters without splitting a `<mark>`. */
function takePlain(source: string, limit: number): string {
  let out = "";
  let used = 0;
  for (const part of source.split(MARK_SPLIT)) {
    if (!part) continue;
    const plainLength = isMarkPart(part)
      ? part.length - MARK_LENGTH
      : part.length;
    if (used + plainLength <= limit) {
      out += part;
      used += plainLength;
      continue;
    }
    if (!isMarkPart(part)) out += part.slice(0, Math.max(limit - used, 0));
    break;
  }
  return out;
}

function truncatePlain(text: string, limit: number): string {
  if (text.length <= limit) return text;
  const cut = text
    .slice(0, limit)
    .replace(/\s+\S*$/, "")
    .replace(/[\s,;:-]+$/, "");
  return `${cut || text.slice(0, limit)}…`;
}

/** Shrink an over-long fragment around its first `<mark>`, ending with `…`. */
function clipFragment(fragment: string): string {
  const flat = fragment.replace(/\s+/g, " ").trim();
  if (stripMarks(flat).length <= PREVIEW_MAX_CHARS) return flat;

  const first = /<mark>.*?<\/mark>/.exec(flat);
  if (!first) return truncatePlain(flat, PREVIEW_MAX_CHARS);

  const before = flat.slice(0, first.index);
  const match = first[0];
  const after = flat.slice(first.index + match.length);

  const budget = Math.max(PREVIEW_MAX_CHARS - (match.length - MARK_LENGTH), 0);
  const keepBefore = Math.floor(budget / 3);
  const keepAfter = budget - Math.min(keepBefore, before.length);

  const clippedBefore =
    before.length > keepBefore
      ? `…${before.slice(before.length - keepBefore).replace(/^\S*\s+/, "")}`
      : before;

  const kept = takePlain(after, keepAfter);
  const wasCut = stripMarks(kept).length < stripMarks(after).length;
  const clippedAfter = wasCut
    ? `${kept.replace(/\s+[^\s<>]*$/, "").replace(/[\s,;:-]+$/, "")}…`
    : kept;

  return `${clippedBefore}${match}${clippedAfter}`;
}

/** The sentence sharing the most words with the query (first one on ties). */
export function bestSentence(text: string, query: string): string | null {
  const cleaned = text.trim();
  if (!cleaned) return null;

  const sentences = cleaned
    .split(/(?<=[.!?])\s+|\n{2,}/)
    .map((sentence) => sentence.trim())
    .filter((sentence) => sentence.length >= 20);
  const candidates = sentences.length > 0 ? sentences : [cleaned];

  const words = (value: string) => value.toLowerCase().match(/\w+/g) ?? [];
  const queryWords = new Set(words(query));
  let best = candidates[0];
  let bestScore = -1;
  for (const sentence of candidates) {
    const score = words(sentence).filter((word) => queryWords.has(word)).length;
    if (score > bestScore) {
      best = sentence;
      bestScore = score;
    }
  }
  return truncatePlain(best.replace(/\s+/g, " "), PREVIEW_MAX_CHARS);
}

function previewFromChunk(chunk: ChunkResult): SearchPreview | null {
  const fragment = chunk.highlights?.find((item) => item.trim().length > 0);
  if (!fragment) return null;

  let line = clipFragment(fragment);
  const plain = stripMarks(fragment);
  const start = chunk.text ? chunk.text.indexOf(plain) : -1;
  if (start > 0 && !line.startsWith("…")) line = `…${line}`;
  if (
    start >= 0 &&
    start + plain.length < chunk.text.length &&
    !line.endsWith("…")
  ) {
    line = `${line}…`;
  }
  return { text: line, kind: "keyword" };
}

function bestChunkScore(file: File): number {
  return Math.max(...(file.chunks ?? []).map((chunk) => chunk.score), 0);
}

/** Preview for one file: a literal match wins, else the best semantic sentence. */
export function buildFilePreview(
  file: File,
  query: string,
): SearchPreview | null {
  const chunks = [...(file.chunks ?? [])].sort((a, b) => b.score - a.score);
  for (const chunk of chunks) {
    const preview = previewFromChunk(chunk);
    if (preview) return preview;
  }
  const top = chunks.find((chunk) => chunk.text?.trim());
  const sentence = top ? bestSentence(top.text, query) : null;
  return sentence ? { text: sentence, kind: "semantic" } : null;
}

/**
 * Previews for the `count` most relevant files, keyed by file identity.
 * Relevance is the best chunk score, so a file with one excellent chunk
 * outranks one with many mediocre chunks.
 */
export function computeTopPreviews(
  files: File[],
  query: string,
  count = TABLE_PREVIEW_FILE_COUNT,
): Map<string, SearchPreview> {
  const previews = new Map<string, SearchPreview>();
  if (!query.trim() || query.trim() === "*") return previews;

  const ranked = files
    .filter((file) => (file.chunks?.length ?? 0) > 0)
    .sort((a, b) => bestChunkScore(b) - bestChunkScore(a))
    .slice(0, count);
  for (const file of ranked) {
    const preview = buildFilePreview(file, query);
    if (preview) previews.set(getKnowledgeFileIdentity(file), preview);
  }
  return previews;
}

/** Split `text` around the first case-insensitive occurrence of `query`. */
export function splitOnQuery(
  text: string,
  query: string,
): { before: string; match: string; after: string } {
  const needle = query.trim().toLowerCase();
  const index = needle ? text.toLowerCase().indexOf(needle) : -1;
  if (index < 0) return { before: text, match: "", after: "" };
  return {
    before: text.slice(0, index),
    match: text.slice(index, index + needle.length),
    after: text.slice(index + needle.length),
  };
}
