# Knowledge Search Test Suite

This test suite is designed to benchmark OpenRAG's search pipeline, hybrid scoring (KNN vs BM25), score normalisation, semantic highlighting, and literal-match gate edge cases.

---

## 📁 Test Documents Summary

| File | Chunk Count / Size Profile | Domain & Focus | Key Characteristics |
| :--- | :--- | :--- | :--- |
| **`01_docling_technical_manual.md`** | 1 large chunk (~2500 chars) | Document processing, OCR, layout extraction, Markdown conversion | Dense technical terms, code samples, tight semantic coupling with "docling" |
| **`02_quantum_computing_primer.md`** | 2 medium chunks (~1200 chars each) | Quantum superposition, qubits, entanglement, Shor's algorithm | Hard science terminology, distinct non-overlapping vocabulary |
| **`03_jobtracker_full_report.md`** | 5 small-to-medium chunks (~500–900 chars) | Relational SQL database, foreign keys, PHP sessions, bcrypt | Multi-chunk document mimicking clean prose/Google Drive exports |
| **`04_culinary_recipes_and_cooking.md`** | 3 varying chunks (~300, 800, 1500 chars) | Baking bread, French sauces, knife techniques | Everyday vocabulary; includes subtle shared terms ("apple", "recipe", "pepper") |
| **`05_medical_cardiology_notes.md`** | 4 chunks (~700 chars each) | Cardiac arrhythmias, ECG interpretation, beta-blockers, cardiology | Dense medical terminology; completely disjoint from CS/IT terms |
| **`06_micro_snippet_single_sentence.md`** | 1 tiny chunk (~80 chars) | Quick system note: "Server status OK" | Tests tiny chunk length bias and boundary edge cases |
| **`07_ambiguous_apple_comparison.md`** | 2 chunks (~900 chars each) | Apple Inc. (tech company) vs Malus domestica (the fruit) | Tests polysemy, ambiguous keyword matching, and cross-domain overlap |
| **`08_pure_numerical_and_logs.md`** | 3 chunks (~600 chars each) | Error codes, UUIDs, stack traces, IP addresses (`192.168.1.1`) | Pure non-natural language, alphanumeric IDs, and stopword-heavy logs |
| **`09_semantic_only_paraphrase.md`** | 6 sections (~200–250 chars each) | Password hashing, cardiac rhythm, OCR pipelines, quantum states, bread-making, job tracking | **Every section uses paraphrase only** — zero keyword overlap with target queries. Pure KNN/vector signal, highlights array will be empty. |
| **`10_semantic_vs_keyword_rank_inversion.md`** | 3 chunks (~200–300 chars each) | Document ingestion pipeline (semantic), keyword spam (BM25 bait), hybrid control | Chunk A = no keywords but strong meaning; Chunk B = keyword spam but weak meaning; Chunk C = hybrid. Demonstrates semantic score > keyword score rank inversion. Use with `01_docling_technical_manual.md`. |

---

## 🔍 Structured Test Query Matrix

Use these predefined query sets to evaluate search precision, rank ordering, and gate filtering.

### Category 1: Tightly Coupled / Exact Keyword Match
*Expected result: Only the target document should appear at High (100%) relevance.*

| Query | Target File | What to Inspect |
| :--- | :--- | :--- |
| `docling` | `01_docling_technical_manual.md` | Ensures `01_docling` ranks #1 and unrelated files are pruned. |
| `qubits` | `02_quantum_computing_primer.md` | Verifies rare scientific terminology exact BM25 match. |
| `bcrypt` | `03_jobtracker_full_report.md` | Verifies security/auth term matches JobTracker chunks. |
| `arrhythmia` | `05_medical_cardiology_notes.md` | Verifies medical terminology precision. |

---

### Category 2: Loosely Related / Semantic Concepts
*Expected result: Hybrid search should retrieve relevant documents based on meaning even with different wording.*

| Query | Expected Matches | What to Inspect |
| :--- | :--- | :--- |
| `database authentication and passwords` | `03_jobtracker_full_report.md` | Semantic alignment with PHP session & SQL security chunks. |
| `document parsing and PDF layout analysis` | `01_docling_technical_manual.md` | Semantic overlap without using the word "docling". |
| `heart rhythm abnormalities and ECG diagnosis` | `05_medical_cardiology_notes.md` | Medical semantic retrieval across cardiology chunks. |
| `quantum physics and superposition algorithms` | `02_quantum_computing_primer.md` | Semantic retrieval on quantum mechanics principles. |

---

### Category 3: Ambiguous / Polysemous Terms
*Expected result: Tests how the engine disambiguates words with multiple meanings.*

| Query | Expected Matches | What to Inspect |
| :--- | :--- | :--- |
| `apple` | `04_culinary_recipes...` & `07_ambiguous_apple...` | Both fruit and tech company documents match, while other 6 files are dropped. |
| `apple macbook silicon` | `07_ambiguous_apple_comparison.md` | Resolves specifically to Apple Inc. tech chunk. |
| `apple pie pastry crust` | `04_culinary_recipes_and_cooking.md` | Resolves specifically to culinary recipe chunk. |

---

### Category 4: Alphanumeric & Code Outliers
*Expected result: Verifies exact code/identifier matching vs noise.*

| Query | Expected Matches | What to Inspect |
| :--- | :--- | :--- |
| `ERR_CONNECTION_REFUSED` | `08_pure_numerical_and_logs.md` | Tests log and symbol search capability. |
| `192.168.1.105` | `08_pure_numerical_and_logs.md` | Tests IP address and dotted token matching. |
| `chk_application_status` | `03_jobtracker_full_report.md` | Tests SQL constraint identifier extraction. |

---

### Category 5: 0-Result Noise / Outliers
*Expected result: Literal gate blocks all files and returns "No results found" overlay.*

| Query | Expected Outcome | What to Inspect |
| :--- | :--- | :--- |
| `xylophone concerto` | 0 results (Overlay shown) | Pure KNN drift suppression. |
| `blockchain crypto bitcoin mining` | 0 results (Overlay shown) | Unrelated tech topic not in test dataset. |
| `astronomy supernova telescope optics` | 0 results (Overlay shown) | Complete semantic and keyword mismatch. |

---

### Category 6: Pure Semantic — No Keyword Match (uses `09_semantic_only_paraphrase.md`)
*Expected result: Chunks from `09` surface with a non-zero score but **empty `highlights` array** and the badge reads "Semantically relevant". The highlighted sentence inside the chunk should be the one most aligned with the query's meaning.*

| Query | Section in `09_semantic_only_paraphrase.md` | What to Inspect |
| :--- | :--- | :--- |
| `password hashing and secure login sessions` | Section A | Chunk appears, badge = "Semantically relevant". `highlights` is empty. The sentence about one-way transformation should be intra-chunk highlighted. |
| `irregular heartbeat and medication to slow heart rate` | Section B | Chunk appears, badge = "Semantically relevant". The sentence about rate-limiting adrenergic medications should be intra-chunk highlighted. |
| `OCR and extracting text from scanned documents` | Section C | Chunk appears, badge = "Semantically relevant". The sentence about pixel-to-glyph conversion should be highlighted. |
| `quantum entanglement and factoring large numbers` | Section D | Chunk appears, badge = "Semantically relevant". The sentence about correlated probability amplitudes and integer factoring should be highlighted. |
| `sourdough bread rising with yeast` | Section E | Chunk appears, badge = "Semantically relevant". The sentence about bulk fermentation and CO₂ expansion should be highlighted. |
| `job application status tracking portal` | Section F | Chunk appears, badge = "Semantically relevant". The sentence about the candidate portal and stage tracking should be highlighted. |

---

### Category 7: Google Drive Files — Semantic & Keyword Parity
*Expected result: Files ingested from Google Drive (`connector_type = "google_drive"`) must behave identically to local files for both keyword and semantic queries. The result card should show the Google Drive icon.*

> **Pre-condition:** Sync at least one Google Drive document that is topically similar to one of the test docs — for example, a Google Doc containing a product changelog (similar to `01_docling`) or a meeting-notes doc (similar to `03_jobtracker`).

| Query | What to Inspect |
| :--- | :--- |
| Exact keyword from synced GDrive doc | File appears in results; badge shows "High relevance" or correct keyword highlight. Google Drive icon is visible on the file row/card. |
| Semantic paraphrase of a concept in the synced GDrive doc | File appears with "Semantically relevant" badge. `highlights` empty. Intra-chunk sentence highlight points to the relevant sentence. |
| Query that matches both a local upload AND a GDrive doc | Both appear in the same result list; relative rank follows score order regardless of connector type. |
| Query unrelated to any GDrive doc | GDrive file is absent; local files that match appear normally. |

---

## 🎨 Semantic Highlight Colour Reference

The UI uses distinct colour tiers to communicate relevance quality at a glance.

### Chunk Badge Colours (Semantic mode)

| Tier | Badge appearance | When shown |
| :--- | :--- | :--- |
| **High** (≥ 65% normalised score) | Deep violet background, white text | Top-ranked semantic chunks |
| **Medium** (35–64%) | Amber/orange background, dark text | Mid-ranked semantic chunks |
| **Low** (< 35%) | Steel-blue/slate background, muted text | Weakly relevant semantic chunks |

### Intra-Chunk Text Highlight Colours

| Situation | Colour | Description |
| :--- | :--- | :--- |
| Keyword literal match | **Yellow** (`bg-yellow-200`) | BM25 term matched; OpenSearch `<mark>` tag present in `highlights` |
| Semantic span — **high** relevance | **Deep violet** (`bg-violet-600` text + strong border) | Pure KNN hit, top-tier normalised score; the most query-relevant sentence is highlighted |
| Semantic span — **medium** relevance | **Medium purple** (`bg-purple-400` text + border) | KNN hit, mid-tier score |
| Semantic span — **low** relevance | **Indigo/blue** (`bg-indigo-200` background) | KNN hit, low-tier score |

> **Key invariant:** A chunk that has no `<mark>` in its `highlights` array but has a non-zero score is always a semantic match. The `isSemanticMatch` flag drives both the badge choice and the intra-chunk sentence highlighting logic in `HighlightedText`.

---

## 🔬 Intra-Chunk Sentence Highlighting — How It Works

When a chunk is a pure semantic match (`highlights` empty, score > 0), `HighlightedText` runs `highlightSemanticSpan`:

1. The chunk text is split into sentences on `.`, `!`, `?`, and newlines.
2. Each sentence is scored against the search query terms (exact token hit = 5 pts, partial stem = 2 pts, content richness bonus).
3. The highest-scoring sentence is wrapped in a `<mark>` styled with the semantic highlight colour; all other sentences render as plain spans.
4. If no sentence scores positively (query tokens don't appear in any form), the first non-noise sentence is highlighted as the best available candidate.

**To verify this is working correctly:** open a chunk from `09_semantic_only_paraphrase.md` after running one of the Category 6 queries. The highlighted sentence should be the one that most directly expresses the concept from the query, even though neither the query words nor the document words are the same.
