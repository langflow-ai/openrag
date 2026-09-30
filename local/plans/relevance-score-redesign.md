# Relevance Score Redesign

## 1 — Why `avg_score` was replaced

OpenSearch returns one `_score` per matched chunk (70% KNN vector similarity + 30% BM25
keyword). The old UI averaged all chunk scores for a file into a single `avg_score` number.
This was misleading in two ways.

**Dilution problem.** A file with one highly relevant chunk and several weakly-matched chunks
shows a low average, even though it contains the answer.

```
Search: "jason"  →  File: JASON_RESUME.pdf

chunk 3 — "Jason has 10 years of experience…"  raw score: 6.0  ← strong hit
chunk 1 — "Skills: Python, Java, …"             raw score: 1.2  ← weak semantic drift
chunk 2 — "References available upon request"   raw score: 0.5  ← near-miss

avg_score = (6.0 + 1.2 + 0.5) / 3 = 2.57  ← looks weak despite a strong hit
```

**Unbounded / uninterpretable scale.** Raw OpenSearch scores have no fixed upper bound and
vary by query, embedding model, and index size. A score of `2.57` means nothing to a user.

---

## 2 — Proposed design: min-max normalization

Scores are normalised relative to the current result set so the best chunk in each query
maps to 100% and the worst maps to 0%. This is always computed at query time on the
frontend after chunks arrive.

Since _score produced by OpenSearch is unbounded, there is no good ceiling threshold to put an absolute max/min normalization, so we stuck with min/max.

### Formula

```
spread        = globalMax − globalMin   (across all chunks in the result set)
normScore(c)  = (c.score − globalMin) / spread    when spread > 0
normScore(c)  = 1.0                               when spread = 0 (single-result guard)
```

### Single-result guard

When only one chunk is returned, `globalMin === globalMax` and dividing by zero is avoided
by returning `1.0` — it is unambiguously the best result for this query.

### Per-file relevance fields

After normalization, each `File` object in the search result carries:

  - `maxScore`:`number | undefined` - Highest normalised chunk score [0, 1] for this file. Undefined for wildcard queries. 
  - `relevanceTier`:`"high" | "medium" | "low" | undefined` - Tier derived from `maxScore`. Undefined for wildcard queries. 
  - `chunkTiers` : `{ high: number, medium: number, low: number }`- Count of matched chunks in each tier. Shown in the tooltip breakdown.

A file's tier is driven by its **best** chunk (`maxScore`), not the average. One strong
chunk makes the whole file "High" regardless of how many weak chunks also matched.

### Tier thresholds (constants in `useGetSearchQuery.ts`)

```ts
export const RELEVANCE_HIGH_THRESHOLD = 0.65;  // normScore ≥ 0.65 → High
export const RELEVANCE_MED_THRESHOLD  = 0.35;  // normScore ≥ 0.35 → Medium, else → Low
```

### Score threshold (constant in `lib/constants.ts`)

```ts
export const SEARCH_CONSTANTS = {
  DEFAULT_SCORE_THRESHOLD: 2.0,  // backend drops chunks below this raw score
};
```

This is the floor that the backend enforces before any chunks reach the frontend.
It was raised from `1.25` to `2.0` after measuring that pure semantic noise clusters around
`1.4–1.9`, meaning the old floor was admitting too many irrelevant chunks.

### Normalised score → tier mapping

| Normalised score | Tier   | Badge colour |
|-----------------|--------|--------------|
| ≥ 0.65          | High   | Emerald      |
| ≥ 0.35          | Medium | Amber        |
| < 0.35          | Low    | Slate/grey   |

---

## 3 — UI: badge + tooltip

```
[ High (88%) ]   ← emerald border/text
[ Medium (50%) ] ← amber border/text
[ Low (12%) ]    ← slate border/text
```

The percentage is `Math.round(maxScore × 100)`. The `Relevance` column is hidden on
wildcard / browse-all queries (no scoring is computed for match_all).

Hovering the badge shows:

```
Relevance breakdown
% = best match for this query in your corpus. A file showing 100%
is the strongest result returned — not necessarily a perfect match.

Total matched chunks: 3
● High: 1
● Medium: 1
● Low: 1
```

---

## 4 — Literal-match gate

Before normalisation, a gate checks whether any meaningful query token appears verbatim
in any returned chunk. If not, the entire result is suppressed and the no-results overlay
is shown instead of a misleading `High (100%)` badge from pure KNN drift.

- Only applied for non-wildcard queries.
- Common English stopwords (~60 tokens) are stripped before the check so queries like
  "your mom" do not pass just because "your" appears in the corpus.
- If the query is entirely stopwords, the gate is skipped (backend score threshold decides).
- `disableLiteralGate: true` bypasses the gate on the single-file chunks view, where the
  user navigated deliberately and expects to see the closest semantic chunks.
- Backend highlights are not used for this check — OpenSearch's fuzzy BM25 can produce
  false-positive highlights (e.g. "convert" for "concerto"). Only raw `chunk.text` is reliable.

---

## 5 — Edge cases and test queries

Upload `local/test-files/relevance-test-corpus.md` to produce a mixed-content corpus
before running these queries.

| # | Query | Tests | Expected result |
|---|---|---|---|
| 1 | `quantum` | Single strong-match term, dilution case | File shows `High` driven by the dense sections; weak sections do not drag the tier down |
| 2 | `quantum error correction surface code` | Multi-word phrase, dense match | File shows `High (100%)` — the best chunk contains all terms at high density |
| 3 | `ocean thermohaline upwelling` | On-topic but only one relevant section in a mixed file | With only one file indexed the best chunk is the global max → `High (100%)`. Add a second dedicated oceanography file and this corpus file will drop to a lower percentage as competition raises the global max |
| 4 | `apple` | Incidental mention vs. strong hit in same result set | Gate passes (literal match). Tier is relative: a file that mentions "apple" once scores `Low (0–5%)` if another file in the result set is strongly about Apple Inc. With no competition, the same file shows `High (100%)`. Min-max is always relative to the query's result set. |
| 5 | `photosynthesis chlorophyll` | Completely absent terms, pure KNN noise | Literal-match gate fires → empty results / no-results overlay shown |
| 6 | `quantum xylophone concerto` | Mixed: one real token, two absent tokens | Gate passes (quantum appears literally); drift chunks score low; file shows the tier of the best quantum chunk |
| 7 | `the` | Single stopword | Gate falls back to checking `"the"` literally — nearly every chunk contains it, so gate passes. Scores vary due to KNN component → real spread → not a zero-spread case. Results appear with genuine tier distribution. |
| 8 | `the a an` | All-stopword query | Same behaviour — all tokens are stopwords so `gateTokens` falls back to the raw tokens; `"the"` appears in corpus so gate passes and results are returned. |
| 9 | Single result returned | Single-result guard — one chunk → spread = 0 | `maxScore = 1.0` → `High (100%)`; correct, it is the best available result for this query |
| 11 | Two files, both strong | Multi-file query where both genuinely match | Both can simultaneously show `High` at different percentages — min-max does not compress either artificially |
| 12 | Short token ≤ 4 chars (e.g. `acme`) | Dynamic threshold cap | `scoreThreshold` is capped at `1.0` regardless of the default, to avoid suppressing all results for short abbreviations |
| 13 | Wildcard `*` or empty string | Browse-all / no search intent | Relevance column hidden; no normalisation computed; `maxScore` and `relevanceTier` are `undefined` |

---

## 6 — Constraints and considerations

**Min-max guarantees a winner.** The best result in every query always reaches `100%`. This
is the trade-off vs. an absolute ceiling: it is honest about relative ranking within the
result set but cannot signal when every result is poor in absolute terms. The literal-match
gate and the backend `DEFAULT_SCORE_THRESHOLD` are the primary guards against an entirely
irrelevant result set reaching the UI.

**Scores are query-scoped, not cross-query comparable.** A file showing `High (78%)` on one
query and `Medium (42%)` on another does not mean it became less relevant — it means the
second query's result set contained stronger competition. Users should be reminded of this
via the tooltip disclaimer.

**Embedding model dependency.** Raw scores vary by model. Raising `DEFAULT_SCORE_THRESHOLD`
above `2.0` would suppress more noise but could also suppress real matches for short or
rare terms. The dynamic cap (`scoreThreshold = min(default, 1.0)` for tokens ≤ 4 chars)
handles the short-token case without a global threshold change.

**Single-worker constraint.** The RBAC permission cache is per-process. Running multiple
uvicorn workers means stale permissions can be served. Unrelated to scoring, but relevant
to any deployment that also uses search results as a permission surface.

**Wildcard queries carry no score.** OpenSearch's `match_all` assigns a constant score
of `1.0` to every document. Normalising these produces meaningless results, so the
`Relevance` column is hidden and `maxScore`/`relevanceTier` are left `undefined` on
wildcard results.

**`chunkTiers` counts matched chunks, not all chunks.** A file with 50 total chunks but
only 3 returned above the score threshold will show `Total matched chunks: 3`. This is
intentional — only scored chunks are in scope; the rest were below the backend floor.
