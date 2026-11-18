import { describe, expect, it } from "vitest";
import type { ChunkResult, File } from "@/app/api/queries/useGetSearchQuery";
import {
  bestSentence,
  buildFilePreview,
  computeTopPreviews,
  expandMarksToWords,
  PREVIEW_MAX_CHARS,
  splitOnQuery,
  stripMarks,
} from "./search-preview";

function chunk(overrides: Partial<ChunkResult> = {}): ChunkResult {
  return {
    filename: "a.pdf",
    mimetype: "application/pdf",
    page: 1,
    text: "body",
    score: 1,
    highlights: [],
    ...overrides,
  };
}

function file(name: string, chunks: ChunkResult[]): File {
  return {
    filename: name,
    mimetype: "application/pdf",
    source_url: "",
    size: 0,
    connector_type: "local",
    chunks,
  };
}

describe("buildFilePreview", () => {
  it("uses the highlight fragment and marks where text was cut away", () => {
    const preview = buildFilePreview(
      file("a.pdf", [
        chunk({
          text: "Intro. The docling library parses PDFs. More follows.",
          highlights: ["The <mark>docling</mark> library parses PDFs"],
        }),
      ]),
      "docling",
    );
    expect(preview?.kind).toBe("keyword");
    expect(preview?.text).toBe(
      "…The <mark>docling</mark> library parses PDFs…",
    );
  });

  it("underlines the whole word when the query only matched its start", () => {
    const preview = buildFilePreview(
      file("a.pdf", [
        chunk({
          text: "Dense retrieval improves recall.",
          highlights: ["Dense <mark>retr</mark>ieval improves recall."],
        }),
      ]),
      "retr",
    );
    expect(preview?.text).toBe("Dense <mark>retrieval</mark> improves recall.");
  });

  it("adds no ellipsis when the fragment is the whole chunk", () => {
    const preview = buildFilePreview(
      file("a.pdf", [
        chunk({
          text: "docling parses PDFs",
          highlights: ["<mark>docling</mark> parses PDFs"],
        }),
      ]),
      "docling",
    );
    expect(preview?.text).toBe("<mark>docling</mark> parses PDFs");
  });

  it("keeps the match and balanced marks when trimming a long fragment", () => {
    const filler = "lorem ipsum ".repeat(40);
    const fragment = `${filler}<mark>needle</mark> ${filler}`;
    const preview = buildFilePreview(
      file("a.pdf", [chunk({ text: fragment, highlights: [fragment] })]),
      "needle",
    );
    expect(preview?.text).toContain("<mark>needle</mark>");
    expect(stripMarks(preview?.text ?? "").length).toBeLessThanOrEqual(
      PREVIEW_MAX_CHARS + 2,
    );
    expect(preview?.text.match(/<mark>/g)).toHaveLength(1);
    expect(preview?.text.match(/<\/mark>/g)).toHaveLength(1);
  });

  it("keeps only a short lead-in so the match sits at the left edge", () => {
    const lead = "alpha beta gamma delta epsilon zeta eta theta iota kappa ";
    const fragment = `${lead}<mark>needle</mark> tail words`;
    const preview = buildFilePreview(
      file("a.pdf", [chunk({ text: fragment, highlights: [fragment] })]),
      "needle",
    );
    const before = (preview?.text ?? "").split("<mark>")[0];
    expect(before.startsWith("…")).toBe(true);
    expect(before.length).toBeLessThanOrEqual(26);
    expect(before).toMatch(/…\S/);
    expect(preview?.text).toContain("<mark>needle</mark> tail words");
  });

  it("keeps a whole word when the lead-in cut lands on a word boundary", () => {
    const word = "b".repeat(23);
    const fragment = `xxxx ${word} <mark>needle</mark>`;
    const preview = buildFilePreview(
      file("a.pdf", [chunk({ text: fragment, highlights: [fragment] })]),
      "needle",
    );
    expect(preview?.text).toBe(`…${word} <mark>needle</mark>`);
  });

  it("prefers the highest-scoring chunk that has a literal match", () => {
    const preview = buildFilePreview(
      file("a.pdf", [
        chunk({ score: 1, highlights: ["low <mark>hit</mark>"] }),
        chunk({ score: 9, highlights: ["high <mark>hit</mark>"] }),
      ]),
      "hit",
    );
    expect(preview?.text).toContain("high");
  });

  it("falls back to the best semantic sentence when nothing matched literally", () => {
    const preview = buildFilePreview(
      file("a.pdf", [
        chunk({
          text: "The weather was pleasant all week. Vector search ranks passages by similarity. Lunch was at noon daily.",
        }),
      ]),
      "passages similarity",
    );
    expect(preview).toEqual({
      kind: "semantic",
      text: "Vector search ranks passages by similarity.",
    });
  });

  it("returns null when the file has no usable text", () => {
    expect(buildFilePreview(file("a.pdf", []), "x")).toBeNull();
    expect(
      buildFilePreview(file("a.pdf", [chunk({ text: "  " })]), "x"),
    ).toBeNull();
  });
});

describe("expandMarksToWords", () => {
  it("grows a partial match to the whole word on either side", () => {
    expect(expandMarksToWords("about <mark>Retr</mark>ieval systems")).toBe(
      "about <mark>Retrieval</mark> systems",
    );
    expect(expandMarksToWords("the pre<mark>fix</mark> match")).toBe(
      "the <mark>prefix</mark> match",
    );
    expect(expandMarksToWords("un<mark>der</mark>line")).toBe(
      "<mark>underline</mark>",
    );
  });

  it("leaves whole-word, non-word-adjacent and CJK marks alone", () => {
    const whole = "a <mark>docling</mark>, parser";
    expect(expandMarksToWords(whole)).toBe(whole);
    expect(expandMarksToWords("検索<mark>エンジン</mark>の")).toBe(
      "検索<mark>エンジン</mark>の",
    );
  });

  it("handles accented words", () => {
    expect(expandMarksToWords("la <mark>reche</mark>rché")).toBe(
      "la <mark>recherché</mark>",
    );
  });
});

describe("bestSentence", () => {
  it("picks the first sentence when none share words with the query", () => {
    expect(
      bestSentence(
        "First sentence is right here. Second one follows it.",
        "zzz",
      ),
    ).toBe("First sentence is right here.");
  });

  it("matches accented and non-Latin words the way the backend does", () => {
    expect(
      bestSentence(
        "Nothing relevant lives in this first sentence. La cafétéria déjà ouverte sert du café.",
        "café",
      ),
    ).toBe("La cafétéria déjà ouverte sert du café.");
    expect(
      bestSentence(
        "Nothing relevant lives in this first sentence. 全文 検索 エンジン の 設計 と 実装 について 説明 する。",
        "エンジン",
      ),
    ).toContain("エンジン");
  });

  it("matches query terms within unspaced CJK text and selects the matching sentence", () => {
    expect(
      bestSentence(
        "関係のない文がここにあります。全文検索エンジンの設計と実装について説明する。もう一つの無関係な文が続きます。",
        "検索",
      ),
    ).toBe("全文検索エンジンの設計と実装について説明する。");
  });

  it("returns null for blank text", () => {
    expect(bestSentence("   ", "q")).toBeNull();
  });

  it("truncates a very long sentence with an ellipsis", () => {
    const long = `${"word ".repeat(100)}end`;
    const result = bestSentence(long, "word") ?? "";
    expect(result.endsWith("…")).toBe(true);
    expect(result.length).toBeLessThanOrEqual(PREVIEW_MAX_CHARS + 1);
  });
});

describe("computeTopPreviews", () => {
  const files = [
    file("low.pdf", [chunk({ score: 1, highlights: ["<mark>q</mark> low"] })]),
    file("top.pdf", [chunk({ score: 9, highlights: ["<mark>q</mark> top"] })]),
    file("mid.pdf", [chunk({ score: 5, highlights: ["<mark>q</mark> mid"] })]),
    file("last.pdf", [chunk({ score: 0.5, highlights: ["<mark>q</mark> x"] })]),
  ];

  it("previews only the three most relevant files", () => {
    const previews = computeTopPreviews(files, "q");
    expect(previews.size).toBe(3);
    const texts = [...previews.values()].map((p) => p.text);
    expect(texts.some((text) => text.includes("top"))).toBe(true);
    expect(texts.some((text) => text.includes("mid"))).toBe(true);
    expect(texts.some((text) => text.includes("low"))).toBe(true);
    // The weakest file is the one left out.
    expect(texts.some((text) => text.endsWith(" x"))).toBe(false);
  });

  it("does not mutate the input order", () => {
    const names = files.map((f) => f.filename);
    computeTopPreviews(files, "q");
    expect(files.map((f) => f.filename)).toEqual(names);
  });

  it("skips top files that only match semantically, without backfilling", () => {
    const mixed = [
      file("semantic.pdf", [
        chunk({ score: 9, text: "Passages ranked by similarity score here." }),
      ]),
      file("keyword.pdf", [
        chunk({ score: 5, highlights: ["<mark>q</mark> hit"] }),
      ]),
      file("also.pdf", [
        chunk({ score: 4, highlights: ["<mark>q</mark> also"] }),
      ]),
      file("fourth.pdf", [
        chunk({ score: 3, highlights: ["<mark>q</mark> fourth"] }),
      ]),
    ];
    const previews = computeTopPreviews(mixed, "q");
    expect(previews.size).toBe(2);
    expect([...previews.values()].every((p) => p.kind === "keyword")).toBe(
      true,
    );
    expect([...previews.values()].some((p) => p.text.includes("fourth"))).toBe(
      false,
    );
  });

  it("ignores highlight fragments that contain no mark", () => {
    const unmarked = [
      file("a.pdf", [chunk({ highlights: ["plain text only"] })]),
    ];
    expect(computeTopPreviews(unmarked, "q").size).toBe(0);
  });

  it("returns nothing for empty and wildcard queries", () => {
    expect(computeTopPreviews(files, "").size).toBe(0);
    expect(computeTopPreviews(files, " * ").size).toBe(0);
  });
});

describe("splitOnQuery", () => {
  it("splits around the first case-insensitive match", () => {
    expect(splitOnQuery("My Docling.pdf", "docling")).toEqual({
      before: "My ",
      match: "Docling",
      after: ".pdf",
    });
  });

  it("returns the whole text as `before` when there is no match", () => {
    expect(splitOnQuery("report.pdf", "zzz")).toEqual({
      before: "report.pdf",
      match: "",
      after: "",
    });
    expect(splitOnQuery("report.pdf", "  ").before).toBe("report.pdf");
  });
});
