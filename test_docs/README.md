# Knowledge Search Test Suite

This test suite is designed to benchmark OpenRAG's search pipeline, hybrid scoring (KNN vs BM25), score normalization, and literal-match gate edge cases.

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
