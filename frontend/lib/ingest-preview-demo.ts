import type { IndexProofChunk } from "@/app/api/queries/useIngestPreviewQuery";

export const SAMPLE_DEMO_FILENAME = "bomarag-ingest-preview-sample.txt";

const SAMPLE_TITLE = "BomaRAG ingest preview sample";

const SAMPLE_INTRO = `This short document demonstrates how files are parsed and
chunked before they are used for retrieval. Nothing from this
sample is saved to your knowledge base.`;

const SAMPLE_STEPS = [
  "Reading layout",
  "Creating chunks",
  "Generating embeddings",
  "Storing in OpenSearch",
] as const;

/** Local sample file for the settings try-out (never uploaded). */
export function createSampleDemoFile(): File {
  const body = [
    SAMPLE_TITLE,
    "",
    SAMPLE_INTRO,
    "",
    ...SAMPLE_STEPS.map((step) => `- ${step}`),
    "",
  ].join("\n");
  return new File([body], SAMPLE_DEMO_FILENAME, { type: "text/plain" });
}

/**
 * Minimal DoclingDocument so DoclingTextPreview can render the sample with the
 * same annotation chrome as a real non-PDF parse.
 */
export function buildSampleDemoDocument(): Record<string, unknown> {
  const texts = [
    { label: "title", text: SAMPLE_TITLE },
    { label: "text", text: SAMPLE_INTRO },
    ...SAMPLE_STEPS.map((step) => ({ label: "list_item", text: step })),
  ];
  return {
    body: texts.map((_, index) => ({ $ref: `#/texts/${index}` })),
    texts,
  };
}

export const SAMPLE_DEMO_STATS = {
  page_count: 1,
  text_count: 2 + SAMPLE_STEPS.length,
  table_count: 0,
  picture_count: 0,
};

export const SAMPLE_DEMO_CHUNKS: IndexProofChunk[] = [
  {
    chunk_id: "demo-chunk-1",
    page: 1,
    text_preview: `${SAMPLE_TITLE}\n\n${SAMPLE_INTRO}`,
    char_count: SAMPLE_TITLE.length + SAMPLE_INTRO.length + 2,
  },
  {
    chunk_id: "demo-chunk-2",
    page: 1,
    text_preview: SAMPLE_STEPS.map((step) => `• ${step}`).join("\n"),
    char_count: SAMPLE_STEPS.map((step) => `• ${step}`).join("\n").length,
  },
];
