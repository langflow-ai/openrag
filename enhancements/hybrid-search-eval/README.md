# Hybrid Search Evaluation — Manual Test Plan

This directory contains a corpus and step-by-step test plan for validating and tuning
the hybrid search normalization pipeline introduced in this branch.

**All scoring constants are in one place:**
[`src/config/search_scoring.json`](../../src/config/search_scoring.json)
Edit that file and restart the backend to retune. No other file needs to change.

---

## Corpus

Six documents in [`corpus/`](corpus/). Upload them all via the Knowledge page before
running any queries. Use default ingest settings (chunk size 1000, overlap 200).

| File | Chars | Chunks | Purpose |
|---|---|---|---|
| `rag_overview.md` | ~2242 | **3** | Multi-chunk semantic target; tests per-chunk scoring and tier distribution |
| `vitamin_c.md` | ~1863 | **3** | Multi-chunk semantic target; tests cross-domain isolation |
| `opensearch_hybrid.md` | ~615 | 1 | Keyword + semantic overlap; tests normalization concepts |
| `sql_query_guide.md` | ~649 | 1 | Exact-token queries; tests BM25 keyword leg |
| `noise_decoy.md` | ~337 | 1 | Internal metadata with SKUs and connection strings; no natural-language topic |
| `cooking_french_onion_soup.md` | ~494 | 1 | Completely unrelated topic; tests cross-domain isolation |

> **Chunking detail:** chunk_size=1000 chars, overlap=200 chars, stride=800 chars.
> `rag_overview.md` splits at chars 0–1000, 800–1800, 1600–2242.
> `vitamin_c.md` splits at chars 0–1000, 800–1800, 1800–1863.
> All other documents are shorter than 1000 chars and index as a single chunk.

---

## Pre-flight checks

Before running queries, confirm the pipeline was created:

1. Open backend logs and search for:
   ```
   "Hybrid search pipeline created/updated"
   ```
   If you see `"Failed to create hybrid search pipeline"` instead, the pipeline is
   absent and scores will not be normalized. Do not proceed until this is resolved.

2. Confirm current constants in `src/config/search_scoring.json`:
   ```json
   {
     "score_threshold": 0.1,
     "semantic_weight": 0.7,
     "keyword_weight": 0.3,
     "relevance_high_threshold": 0.65,
     "relevance_med_threshold": 0.35,
     "relevance_hide_threshold": 0.1
   }
   ```

---

## Test cases

For each test: enter the query, observe results, record the `maxScore` visible in the
relevance tooltip and the tier label (High / Medium / Low) on the top file.

### Group 1 — Semantic relevance (no exact keyword matches expected)

These queries use words that do not appear verbatim in the documents. Only the semantic
(k-NN) leg should carry the result. They validate that the 70% semantic weight is working
and that scores are in [0, 1] after the normalization processor.

---

**T1 — RAG concept, paraphrased**
```
how does retrieval augmented generation reduce hallucination
```
| Expected | Details |
|---|---|
| Top file | `rag_overview.md` |
| Tier | High |
| Keyword highlights | None (semantic-only match — no `<mark>` tags) |
| `cooking_french_onion_soup.md` | Should not appear |
| Score range | `maxScore` should be 1.0 (best result in set gets normalized to 1.0 by frontend) |

✅ Pass / ❌ Fail — notes: ___________

---

**T2 — Vitamin concept, paraphrased**
```
what vitamin deficiency causes bone disease in children
```
| Expected | Details |
|---|---|
| Top file | `vitamin_c.md` (Vitamin D / rickets section) |
| Tier | High |
| Keyword highlights | None |
| `rag_overview.md` | Should not appear or be Low tier |

✅ Pass / ❌ Fail — notes: ___________

---

**T3 — Rare word, semantic reach**
```
what causes scurvy
```
| Expected | Details |
|---|---|
| Top file | `vitamin_c.md` |
| Tier | High |
| Note | "scurvy" appears verbatim — expect both keyword highlights AND semantic score. |
|      | Good test of combined scoring: both legs should fire. |

✅ Pass / ❌ Fail — notes: ___________

---

**T4 — Cross-domain isolation**
```
how to caramelise onions for soup
```
| Expected | Details |
|---|---|
| Top file | `cooking_french_onion_soup.md` |
| Tier | High |
| `rag_overview.md` | Must not appear |
| `vitamin_c.md` | Must not appear |

✅ Pass / ❌ Fail — notes: ___________

---

### Group 2 — Keyword precision (BM25 leg)

These queries contain exact tokens from the documents. The keyword leg should produce
highlights. Validates that the 30% keyword weight contributes meaningfully.

---

**T5 — Normalization processor terminology**
```
normalization processor min_max arithmetic_mean
```
| Expected | Details |
|---|---|
| Top file | `opensearch_hybrid.md` |
| Tier | High |
| Keyword highlights | Yes — `normalization`, `min_max`, `arithmetic_mean` should be highlighted |

✅ Pass / ❌ Fail — notes: ___________

---

**T6 — SQL error code**
```
ERROR 1062 duplicate entry
```
| Expected | Details |
|---|---|
| Top file | `sql_query_guide.md` |
| Tier | High |
| Keyword highlights | Yes — `ERROR`, `1062`, `duplicate` should be highlighted |
| `rag_overview.md` | Must not appear |

✅ Pass / ❌ Fail — notes: ___________

---

**T7 — Oracle error code (exact token)**
```
ORA-00942
```
| Expected | Details |
|---|---|
| Top file | `sql_query_guide.md` |
| Tier | High |
| Note | Exact-token path. Hyphen triggers exact-match detection in `_is_exact_token_query`. |
| Keyword highlights | Yes |

✅ Pass / ❌ Fail — notes: ___________

---

**T8 — Internal SKU / ticket number**
```
PROJ-4471
```
| Expected | Details |
|---|---|
| Top file | `noise_decoy.md` |
| Tier | High or Medium |
| Note | SKU-like string; only one document contains it. |
| Keyword highlights | Yes |

✅ Pass / ❌ Fail — notes: ___________

---

### Group 3 — Semantic weight vs keyword weight

These tests validate that semantic carries results when there is no keyword overlap,
and that keyword does not falsely elevate unrelated documents.

---

**T9 — Semantic-only, no exact match**
```
daily recommended intake of ascorbic acid supplements
```
| Expected | Details |
|---|---|
| Top file | `vitamin_c.md` |
| Tier | High |
| Keyword highlights | None or minimal — "acid" may match but is not a primary hit driver |
| Note | "ascorbic acid" appears in `vitamin_c.md`. If it shows highlights, that is fine. |
|      | If `rag_overview.md` appears — semantic bleed, check embedding quality. |

✅ Pass / ❌ Fail — notes: ___________

---

**T10 — Weighted blending sanity check**
```
vector index nearest neighbours embedding model inference
```
| Expected | Details |
|---|---|
| Top file | `rag_overview.md` |
| Tier | High |
| Keyword highlights | Yes for `embedding`, `model`; semantic also fires |
| Note | Both legs should contribute. This is the ideal hybrid hit. |
|      | Check that `opensearch_hybrid.md` is also present (it covers similar concepts) |
|      | but that `rag_overview.md` ranks higher due to more content depth. |

✅ Pass / ❌ Fail — notes: ___________

---

### Group 4 — Multi-chunk scoring

These tests are only meaningful for `rag_overview.md` (3 chunks) and `vitamin_c.md`
(3 chunks). They validate that `maxScore` and `chunkTiers` work correctly.

---

**T11 — Top chunk vs lower chunks**
```
retrieval augmented generation
```
| Expected | Details |
|---|---|
| Top file | `rag_overview.md` |
| Chunk count | 3 shown in the file row |
| Tier counts | Open the relevance tooltip — should show at least 1 High chunk |
| `maxScore` | 1.0 (top chunk normalised to 1.0 by frontend min-max) |
| Note | Individual chunk scores will differ. The file's tier is derived from its |
|      | highest-scoring chunk, not an average. |

✅ Pass / ❌ Fail — notes: ___________

---

**T12 — Query targeting a specific chunk section**
```
scurvy fatigue gum disease
```
| Expected | Details |
|---|---|
| Top file | `vitamin_c.md` |
| Note | The scurvy content is in chunk 1 (chars 0–1000). Chunk 2 and 3 cover |
|      | Vitamin D and antioxidant mechanisms. Expect chunk 1 to score highest, |
|      | chunks 2–3 to be Medium or Low. Check the tooltip tier counts. |

✅ Pass / ❌ Fail — notes: ___________

---

### Group 5 — Noise and stopword suppression

---

**T13 — Keyboard mash**
```
asdfghjkl
```
| Expected | Details |
|---|---|
| Results | Zero results |
| Note | Noise query — semantic leg is suppressed. BM25 finds no match. |
|      | If results appear, `score_threshold` needs to be raised. |

✅ Pass / ❌ Fail — notes: ___________

---

**T14 — Keyboard row**
```
qwerty
```
| Expected | Details |
|---|---|
| Results | Zero results |

✅ Pass / ❌ Fail — notes: ___________

---

**T15 — Single stopword**
```
the
```
| Expected | Details |
|---|---|
| Results | Zero results, or all results are Low tier |
| Note | "the" is a single token so stopword stripping does not fire (only strips from |
|      | multi-word queries). BM25 may return some results. If they appear, check their |
|      | scores — they should be Low tier and below `relevance_med_threshold`. |

✅ Pass / ❌ Fail — notes: ___________

---

### Group 6 — Wildcard (baseline / regression)

---

**T16 — Wildcard shows all documents**
```
*
```
| Expected | Details |
|---|---|
| Results | All 6 documents appear |
| Scores | No score shown (wildcard path has no scoring) |
| Note | This path bypasses hybrid entirely. Confirms ingest worked for all docs. |

✅ Pass / ❌ Fail — notes: ___________

---

## Tuning guide

After running all tests, use these rules to adjust `src/config/search_scoring.json`:

| Symptom | Fix |
|---|---|
| T13/T14 return results | Raise `score_threshold` (try 0.15, 0.2) |
| T3/T4/T9 return 0 results | Lower `score_threshold` (try 0.05) |
| T1–T4 all land as Medium or Low | Lower `relevance_high_threshold` (try 0.55) |
| T10 shows `cooking_french_onion_soup.md` in top results | Semantic bleed; consider raising `semantic_weight` to 0.75 |
| T6/T7 do not show keyword highlights | BM25 leg not firing; check `keyword_weight` is > 0 and pipeline PUT succeeded |
| Tier counts in T11/T12 tooltip show all High | Lower `relevance_high_threshold` or raise `relevance_med_threshold` |

After any change: restart the backend only (no OpenSearch restart needed for threshold
changes). The pipeline weights (`semantic_weight`, `keyword_weight`) require a backend
restart to update the pipeline definition in OpenSearch.

---

## Score interpretation

With the normalization processor active, `_score` from OpenSearch is always in `[0, 1]`.
The frontend min-max pass then re-anchors the result set so the top result is always 1.0
and the lowest is 0.0. The tier thresholds apply to this re-anchored value:

```
normalizedScore >= 0.65  →  High
normalizedScore >= 0.35  →  Medium
normalizedScore >= 0.10  →  Low (shown)
normalizedScore <  0.10  →  hidden (RELEVANCE_HIDE_THRESHOLD)
```

A `maxScore` of 1.0 on the top file is always expected — it means that file's best chunk
was the top result in the set. A file with `maxScore` of 0.4 means its best chunk scored
roughly midway between the worst and best chunk in the entire result set.
