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
const TABLE_PREVIEW_FILE_COUNT = 3;

export interface SearchPreview {
  /** One line; `keyword` previews wrap matched terms in `<mark>`. */
  text: string;
  kind: "keyword" | "semantic";
}

const CJK_REGEX =
  /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]/u;

const MARK_LENGTH = "<mark></mark>".length;
const MARK_SPLIT = /(<mark>.*?<\/mark>)/;

export function stripMarks(fragment: string): string {
  return fragment.replace(/<\/?mark>/g, "");
}

const WORD_CHARS = "[\\p{L}\\p{N}_]";
const MARK_THEN_WORD_TAIL = new RegExp(
  `<mark>([^<]*)</mark>(${WORD_CHARS}+)`,
  "gu",
);
const WORD_HEAD_THEN_MARK = new RegExp(
  `(${WORD_CHARS}+)<mark>([^<]*)</mark>`,
  "gu",
);

/**
 * Grow each `<mark>` to the whole word it sits in, so a partial query such as
 * "retr" underlines "retrieval". CJK text has no word boundaries, so it is left alone.
 */
export function expandMarksToWords(fragment: string): string {
  const unlessCjk = (extra: string, whole: string, grown: string) =>
    CJK_REGEX.test(extra) ? whole : grown;
  return fragment
    .replace(MARK_THEN_WORD_TAIL, (whole, marked, tail) =>
      unlessCjk(tail, whole, `<mark>${marked}${tail}</mark>`),
    )
    .replace(WORD_HEAD_THEN_MARK, (whole, head, marked) =>
      unlessCjk(head, whole, `<mark>${head}${marked}</mark>`),
    );
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

/**
 * Text kept ahead of the first match. The table cell is far narrower than
 * `PREVIEW_MAX_CHARS`, so the CSS ellipsis would otherwise land on the match.
 */
const PREVIEW_LEAD_CHARS = 24;

/** Last `limit` characters of `text`, starting on a word boundary, with a leading `…` when cut. */
function trimLead(text: string, limit: number): string {
  if (text.length <= limit) return text;
  const tail = text.slice(text.length - limit);
  const startsOnWord = /\s/.test(text[text.length - limit - 1] ?? "");
  return `…${startsOnWord ? tail : tail.replace(/^\S*\s+/, "")}`;
}

/**
 * Shrink a fragment around its first `<mark>`: a short lead-in so the match
 * sits at the left edge of the cell, and a tail ending with `…` when long.
 */
function clipFragment(fragment: string): string {
  const flat = fragment.replace(/\s+/g, " ").trim();

  const first = /<mark>.*?<\/mark>/.exec(flat);
  if (!first) return truncatePlain(flat, PREVIEW_MAX_CHARS);

  const match = first[0];
  const after = flat.slice(first.index + match.length);
  const clippedBefore = trimLead(
    flat.slice(0, first.index),
    PREVIEW_LEAD_CHARS,
  );

  const keepAfter = Math.max(
    PREVIEW_MAX_CHARS -
      stripMarks(clippedBefore).length -
      (match.length - MARK_LENGTH),
    0,
  );
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
    .split(/(?<=[.!?])\s+|(?<=[。！？])\s*|\n{2,}/)
    .map((sentence) => sentence.trim())
    .filter(
      (sentence) =>
        sentence.length >= 20 ||
        (CJK_REGEX.test(sentence) && sentence.length >= 8),
    );
  const candidates = sentences.length > 0 ? sentences : [cleaned];

  const words = (value: string) =>
    value.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? [];
  const queryWords = new Set(words(query));
  let best = candidates[0];
  let bestScore = -1;
  for (const sentence of candidates) {
    const sLower = sentence.toLowerCase();
    const sentenceWords = new Set(words(sentence));
    let score = 0;
    for (const queryWord of queryWords) {
      if (
        sentenceWords.has(queryWord) ||
        (CJK_REGEX.test(queryWord) && sLower.includes(queryWord))
      ) {
        score++;
      }
    }
    if (score > bestScore) {
      best = sentence;
      bestScore = score;
    }
  }
  return truncatePlain(best.replace(/\s+/g, " "), PREVIEW_MAX_CHARS);
}

function previewFromChunk(chunk: ChunkResult): SearchPreview | null {
  const fragment = chunk.highlights?.find((item) => item.includes("<mark>"));
  if (!fragment) return null;

  let line = clipFragment(expandMarksToWords(fragment));
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
 * Keyword previews for the `count` most relevant files, keyed by file identity.
 * Relevance is the best chunk score, so a file with one excellent chunk
 * outranks one with many mediocre chunks. A top file without a literal match
 * gets no preview; the slot is not passed down to the next file.
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
    // A semantic guess carries no underlined match, so it is not worth a row.
    if (preview?.kind === "keyword") {
      previews.set(getKnowledgeFileIdentity(file), preview);
    }
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
