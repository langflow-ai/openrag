# Search score normalization

How a search result's relevance score becomes the `0–100%` number and the
High / Medium / Low tier you see in the Knowledge table.

## The one rule

**The backend always hands the frontend scores in `[0, 1]`. The frontend trusts
them and never re-scales.**

Everything below is just how the backend keeps that promise on every search path.

## Why this exists

We used to normalize **twice**: OpenSearch normalized scores, then the frontend
min-max'd them *again* across whatever came back. That double-stretch forced the
best result to always look like 100% and the worst like 0%, even when every hit
was actually a strong (or weak) match — the percentage didn't mean much.

Now there is a single source of truth: the backend.

## How the backend normalizes

| Search path | Who normalizes | Result |
| --- | --- | --- |
| Normal hybrid (keyword + vector), no DLS | OpenSearch `openrag_hybrid_pipeline` | Weighted blend (70% semantic / 30% keyword), already `[0, 1]` |
| **Lucene-level DLS** (owner-based, no terms-lookup) | OpenSearch `openrag_hybrid_pipeline` | Pipeline runs normally — weighted `[0, 1]` |
| **Filter-level DLS** (terms-lookup, e.g. the ACL role) | Backend, in Python | **Emulates** the pipeline's weighted per-leg blend (within ~1–2% of it) |
| Keyword-only (no embeddings available) | Backend, in Python | Raw scores min-max'd to `[0, 1]` |
| Wildcard `*` | nobody | Uniform scores, **not** a relevance signal |

The backend reports which path produced the scores via the `normalized` field:

- `"pipeline"` → the OpenSearch pipeline normalized them (weighted). Used as-is.
- `"default"` → the backend min-max normalized them (filter-level DLS or
  keyword-only), or there is no relevance signal (wildcard). Used as-is.
- flag absent (website-page view, older backend) → the frontend falls back to its
  own min-max so nothing ever renders a raw score like `687%`.

### When the pipeline is bypassed (and when it isn't)

OpenSearch's hybrid pipeline is the *better* normalizer — it blends the keyword
and vector legs with weights. Whether it runs under DLS depends on the **DLS
evaluation mode** (verified on OpenSearch 3.9):

- **Lucene-level DLS** (owner-based filters, no terms-lookup): the pipeline runs
  normally — a DLS user gets the same weighted `[0, 1]` scores as an admin.
- **Filter-level DLS**: the security plugin wraps the query and the pipeline is
  **silently bypassed** — hits come back with raw, unbounded scores (e.g.
  `6.87, 4.65…` instead of `0.7, 0.32…`), no error.

A DLS query runs at filter-level whenever it contains a **terms-lookup**. OpenRAG's
ACL role (`openrag_user_acl_role`) resolves shared-document access with a
terms-lookup against `openrag_dls_principals`, so **any user mapped to the ACL
role is in filter-level mode and loses the pipeline**.

### Emulating the pipeline for bypassed users

Rather than fall back to a raw min-max (which is keyword-dominated), the backend
**reconstructs the pipeline's math** for those users. The hybrid query names its
two legs, and `include_named_queries_score` makes OpenSearch return each leg's
score per hit even when the pipeline is bypassed. The backend then does what the
pipeline would have: min-max each leg independently across the returned hits, then
combine `SEMANTIC_WEIGHT · semantic + KEYWORD_WEIGHT · keyword` (a leg a hit didn't
match contributes 0). Validated against the real pipeline on identical inputs: the
scores agree to within ~1–2% and the **ranking is identical**, so a filter-level
DLS user sees essentially the same relevance as everyone else. This all happens in
the original request — no extra round-trip. (Keyword-only search has no vector leg,
so it stays on a plain combined min-max.)

### Why keep the pipeline at all, if we can emulate it?

The backend only *needs* to emulate when the pipeline is bypassed. When it runs
natively (non-DLS and lucene-level DLS) it is cheaper and authoritative, so we use
it and skip the Python work. The emulation exists to give *filter-level DLS* users
the same weighted result without a second query — not to replace the pipeline.

### Why keyword-only stays on the Python path

Keyword-only search has no vector leg, so there is nothing to weight — pipeline
min-max and Python min-max produce the same `[0,1]` result. Wrapping it in a
single-sub-query hybrid would also clash with the pipeline's two-element weight
array. The Python path is simpler and equivalent, so keyword-only is left as a
plain `bool` query and normalized in Python.

## Where things live

- **Thresholds / weights** — `src/config/search_scoring.json` (single source of
  truth; both backend and frontend read it). Edit here to retune.
- **The pipeline definition** — `src/utils/opensearch_init.py`
  (`min_max` normalize + `arithmetic_mean` combine with the configured weights).
- **Backend normalization + flag** — `src/services/search_service.py`
  (`_ensure_normalized_scores`, and the `normalized` field on the response).
- **Frontend trust/fallback** — `frontend/app/api/queries/useGetSearchQuery.ts`
  (reads `data.normalized`).
- **Tier cutoffs in the UI** — `frontend/components/relevance-signal-icon.tsx`
  (`getScoreTier`, now reading the shared thresholds instead of hardcoded 65/35).

## What changed in this work

1. **Removed the double normalization.** The frontend no longer min-max's scores
   when the backend already normalized them.
2. **Backend now guarantees `[0, 1]` on every path**, including filter-level DLS
   and keyword-only, via `_ensure_normalized_scores`, and reports which path ran
   with the `normalized` field (`"pipeline"` or `"default"`).
3. **Filter-level DLS users get the weighted blend emulated** (`_emulate_pipeline_scores`)
   from per-leg scores (`include_named_queries_score`), so their ranking matches the
   native pipeline instead of being keyword-dominated.
4. **Removed dead code** — the unused `avgScore` field/column helpers and a
   redundant third min-max in the file-chunks panel.
5. **Config cleanup** — the UI tier cutoffs (65 / 35) now come from
   `search_scoring.json` instead of being hardcoded.

## Why the top result isn't always 100%

The two paths differ in whether scores span the full 0–100%:

- **`"pipeline"` scores:** each leg (vector, keyword) is min-max'd *separately*,
  then blended `0.7·semantic + 0.3·keyword`. A score of 100% requires one
  document to top **both** legs at once, which is rare — so the best result is
  usually below 100% (e.g. a pure semantic winner lands at `0.7 × 1.0 = 70%`).
  The low end is trimmed by `score_threshold`, so 0% rarely shows either.
- **`"default"` scores:** for filter-level DLS, the backend *emulates* the same
  weighted blend, so the numbers track `"pipeline"` within ~1–2% and the best
  result is usually below 100% too. For keyword-only search (no vector leg) it is a
  plain min-max of the one leg, so the best result is ~100%.

Judge relevance by **ordering and tier** rather than the exact number — small
percentage differences between the pipeline and its emulation are expected.

## Known limitation

The emulation normalizes over the **returned hits**, while the pipeline normalizes
over its larger internal candidate set, so filter-level DLS scores differ from the
native pipeline by ~1–2% (ranking is preserved). The residual shrinks as the result
`limit` grows. Keyword-only search has no vector leg to weight, so it keeps a plain
combined min-max. Both are inherent, not bugs.
