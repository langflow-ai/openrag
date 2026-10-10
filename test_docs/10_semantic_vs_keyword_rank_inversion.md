# Rank Inversion Walkthroughs: Semantic Score > Keyword Score

These walkthroughs demonstrate cases where a chunk with **no literal query keywords**
outranks a chunk that contains the exact query words. All scenarios use the existing
test documents — no extra uploads needed beyond the standard suite.

---

## How to read the expected results

- **Indigo badge** = "Semantically relevant (N%)" — KNN only, `highlights` empty
- **Emerald/amber badge** = "N% relevance" — keyword match, `<mark>` visible in text
- A semantic chunk outranking a keyword chunk means the indigo % > the amber %

---

## Walkthrough 1 — The clearest rank inversion

**Search:** `password hashing and secure login sessions`

**Expected for `09_semantic_only_paraphrase.md` (Section A):**
- Badge: **indigo "Semantically relevant (~60–90%)"**
- Highlights: none
- Visible sentence highlight on: *"a one-way transformation is applied before writing the value to the record store"*
- Why: The chunk describes bcrypt/hashing exactly — but uses none of those words

**Expected for `03_jobtracker_full_report.md`:**
- Badge: **emerald/amber "N% relevance"** with `<mark>` on `password`, `hash`, `session`
- Visible marks on: `password_hash()`, `bcrypt`, `HttpOnly`, `SameSite`
- Why: Literal keyword match on "password" and related terms

**The rank inversion to observe:**
The `09` chunk (indigo, zero keyword marks) may show a **higher % than the `03` chunk**
despite `03` containing the words "password", "bcrypt", "session" literally.
The embedding model scored `09` higher because its entire paragraph is semantically
dense around credential security — the concept vector aligns more tightly with
the query than a chunk where "password" appears once among SQL schema definitions.

---

## Walkthrough 2 — Semantic beats exact scientific term

**Search:** `irregular heartbeat treatment and slowing heart rate`

**Expected for `09_semantic_only_paraphrase.md` (Section B):**
- Badge: **indigo "Semantically relevant (~50–85%)"**
- Highlights: none
- Visible sentence highlight on: *"Rate-limiting medications that antagonise adrenergic receptors are frequently prescribed to slow conduction"*
- Why: Describes beta-blockers and arrhythmia treatment with zero overlap on query terms

**Expected for `05_medical_cardiology_notes.md`:**
- Badge: **emerald/amber "N% relevance"** with `<mark>` on `heart`, `rate`, `irregular`
- Marks visible on: `irregular ventricular response`, `rate control`, `Metoprolol`
- Why: Literal matches on "heart", "rate", and "irregular"

**The rank inversion to observe:**
`09` Section B (indigo) may outrank the `05` keyword hit because the entire `09`
paragraph is about slowing heart rate via medication — that's a tighter concept
match than a `05` chunk that mentions "heart rate" as one item in a list of
diagnostic criteria.

---

## Walkthrough 3 — Hybrid hit vs pure semantic (the flash you saw explained)

**Search:** `OCR text extraction from scanned documents`

**Expected for `01_docling_technical_manual.md`:**
- Badge: **emerald "High (80–100%)"** with `<mark>` on `OCR`, `scanned`, `document`
- This is the **hybrid control** — strong KNN AND BM25 both fire
- The score is high because KNN (70% weight) and BM25 (30% weight) both contributed

**Expected for `09_semantic_only_paraphrase.md` (Section C):**
- Badge: **indigo "Semantically relevant (~40–70%)"**
- Highlights: none
- Visible sentence highlight on: *"Pipelines that ingest physical or photographed documents must first resolve pixel grids into glyph sequences"*
- Why: Pure KNN — "pixel grids into glyph sequences" = OCR, no literal term

**The flash you observed — explained:**
When you click into a file, `hlFile` (file-scoped search) loads first. That request
only sees this one file's chunks, so its min-max normalisation makes the top chunk
100% and flags it semantic (indigo). Then `globalFile` (the knowledge-page cache,
all files) loads and overwrites — the same chunk is now scored relative to ALL
chunks across all files, so its normalised % drops and its tier may shift.
This is correct behaviour. The final stable state (after the flash) is the accurate
globally-comparable score.

---

## Walkthrough 4 — Keyword spam loses to meaning (the test doc scenario)

**Search:** `document parsing pipeline`

**Expected for `10_semantic_vs_keyword_rank_inversion.md` Chunk A:**
- Badge: **indigo "Semantically relevant"**
- Highlights: none
- Why: Describes a document ingestion layout graph — strong concept vector

**Expected for `10_semantic_vs_keyword_rank_inversion.md` Chunk B:**
- Badge: **low % relevance** with `<mark>` on `parsing`
- Despite "parsing tools" appearing 6× literally, the score is **lower** than Chunk A
- Why: KNN (70% weight) returns near-zero for semantically empty text; BM25 (30%)
  fires but cannot overcome the KNN penalty

**Expected for `10_semantic_vs_keyword_rank_inversion.md` Chunk C:**
- Badge: **emerald high % relevance** with `<mark>` on `parsing`, `document`, `tools`
- This ranks **above both** — hybrid hit with strong KNN AND BM25
- Why: Real technical content about parsing pipelines + literal keyword matches

**Note:** If `01_docling_technical_manual.md` is also ingested, its chunks will
likely dominate at the top because they are denser and more semantically aligned.
Chunk A from `10` should still outrank Chunk B from `10` — that's the inversion.

---

## What "only relevance, no purple" means

If you see only emerald/amber badges and no indigo across all results, it means
every returned chunk had at least one `<mark>` keyword hit. This is expected when:

1. The query terms are common enough that BM25 finds literal matches everywhere
2. Your corpus is small and a few files contain the exact words
3. The semantic-only files (`09`) haven't been ingested yet

**To force purple (semantic) badges to appear:**
- Make sure `09_semantic_only_paraphrase.md` is ingested
- Use one of the Walkthrough 1 or 2 queries above — those are calibrated to have
  `09` return chunks with no keyword overlap
- If you still see only emerald, check that embeddings are enabled (the provider
  health indicator in the top bar should be green)
