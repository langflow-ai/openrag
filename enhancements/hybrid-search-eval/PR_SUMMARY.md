# Hybrid Search Overhaul — PR Summary

**Branch:** `overhaul/avg_score` → `main`
**Scope:** 71 files, ~4,600 insertions / ~530 deletions

## TL;DR

Search relevance scoring was rebuilt end to end. Previously the "70% semantic /
30% keyword" split was only nominal — raw BM25 keyword scores are unbounded and
dwarfed the semantic signal, so ranking was effectively keyword-first. This PR
introduces a real, weighted hybrid blend via an OpenSearch normalization
pipeline, makes the backend the single source of truth for `[0,1]` relevance
scores on every search path (including DLS and keyword-only), and surfaces
High/Medium/Low relevance tiers in the Knowledge UI.

> **One knob for all numbers:** every tunable scoring value — weights,
> threshold, tier cutoffs, pipeline name — now lives in a single file,
> `src/config/search_scoring.json`, read by **both** the backend and the
> frontend. Retuning relevance is a one-line edit, no code change.
>
> **Frontend no longer normalizes:** the UI used to min-max the scores a second
> time on top of whatever the backend returned. That double-normalization is
> removed — the frontend now trusts the backend's `[0,1]` score directly.

Net effect on our retrieval eval (83 questions, 21 docs): **top-rank precision
improved across the board** (recall@1 +1.8pts, MRR +1.5pts, nDCG@1 +2.4pts,
passage hit@1 +5.2pts) at a **small cost to deep recall** (recall@5 −0.6pts,
recall@10 −1.2pts). The right answer is now ranked #1 more often; a couple of
questions lost a hit deep in the list. The trade is deliberate and tunable.

---

## What changed

### 1. Backend ranking — real weighted hybrid search
- Replaced the old `bool/should` query (which summed raw, mismatched-scale
  BM25 + kNN scores) with a true OpenSearch **`hybrid` query** run through a new
  **normalization pipeline** (`openrag_hybrid_pipeline`).
- The pipeline **min-max normalizes each leg to `[0,1]` independently**, then
  combines them `0.7·semantic + 0.3·keyword` — so the semantic/keyword split is
  now meaningful regardless of raw score scale.
- Pipeline is created/updated idempotently on startup
  (`ensure_hybrid_search_pipeline` in `src/utils/opensearch_init.py`), so
  weight changes take effect on next boot with no manual cleanup.

### 2. Backend scoring is the single source of truth (`[0,1]` on every path)
- `_ensure_normalized_scores` + `_emulate_pipeline_scores` guarantee every
  non-wildcard search returns scores in `[0,1]`, and the response reports which
  path produced them via a new `normalized` field (`"pipeline"` / `"default"`).
- **Filter-level DLS users** (anyone on the ACL role via terms-lookup) silently
  bypass the OpenSearch pipeline. Rather than fall back to keyword-dominated raw
  scores, the backend now **emulates the pipeline's weighted blend in Python**
  from per-leg scores (`include_named_queries_score`) — ranking matches the
  native pipeline within ~1–2%, with no extra round-trip.
- Added a **DLS bool/should fallback**: on clusters where the security plugin's
  `function_score` wrapper rejects a top-level hybrid query, the search retries
  as `bool/should` instead of failing.

### 3. Query hardening
- **Stopword stripping on the keyword leg** (`_keyword_query`) — filler words no
  longer dilute keyword matching; the semantic leg still embeds the full query.
- **Noise/gibberish detection** (`_is_noise_query`) — keyboard-mash queries skip
  the semantic leg entirely, so garbage input can't match arbitrary chunks via
  nearest-neighbor.
- **Readable-text filter** — drops chunks with no real words (e.g. markdown
  table rules) from results.
- `minimum_should_match: "2<75%"` added to the keyword leg; `num_candidates`
  removed from kNN clauses (jvector/engine uses `k` only).

### 4. Score threshold handling
- Threshold is now applied as a **Python post-filter on pipeline-normalized
  `[0,1]` scores** (default `0.1`), instead of a top-level `min_score` that the
  DLS constant-score clause was quietly defeating.

### 5. Frontend — trust the backend, show relevance tiers
- Frontend **no longer re-normalizes** scores when the backend already did
  (the old double min-max forced the best hit to always look like 100% and the
  worst like 0%). It reads `data.normalized` and trusts the score; min-max
  fallback only runs for legacy/absent-flag responses.
- New **High / Medium / Low relevance tiers** and a low-relevance banner in the
  Knowledge table, plus per-file chunk-tier breakdown in the tooltip
  (`relevance-signal-icon.tsx`, `low-relevance-banner.tsx`).
- Removed the dead `avgScore` field/column and a redundant third min-max in the
  file-chunks panel.

### 6. Config consolidation
- All tunable scoring values now live in one file — **`src/config/search_scoring.json`**
  (pipeline name, score threshold, semantic/keyword weights, tier cutoffs).
  Both backend (`search_constants.py`) and frontend (`lib/constants.ts`) read it,
  so retuning is a one-file edit.

### 7. Tests & eval harness
- New/expanded unit suites: `test_hybrid_search_query.py` (648 lines),
  `test_search_service_noise.py`, `test_search_service_highlights.py`,
  overhauled `test_search_service_score_threshold.py`, plus frontend tests for
  the new tier/banner/normalization logic.
- Added the **retrieval eval harness and corpus** under
  `enhancements/hybrid-search-eval/` and `tests/fixtures/search_corpus/`, with a
  documented scoring design (`SCORE_NORMALIZATION.md`).

---

## The two normalization paths

Every non-wildcard search returns scores in `[0,1]`, but they are produced one
of two ways. The response advertises which via a new `normalized` field, and the
frontend trusts both equally:

**1. `"pipeline"` — OpenSearch normalizes (the preferred path).**
The `openrag_hybrid_pipeline` min-max normalizes the k-NN leg and the BM25 leg
*independently*, then combines them `0.7·semantic + 0.3·keyword`. This is the
authoritative, cheaper path and runs for all non-DLS users and for owner-based
("lucene-level") DLS users. A side effect worth knowing: because each leg is
normalized separately, a result scores 100% only if it tops **both** legs at
once — so a pure semantic winner lands around 70%, not 100%. Judge by tier and
ordering, not the exact percentage.

**2. `"default"` — the backend normalizes (fallback paths).**
Used when the pipeline can't run:
- **Filter-level DLS** (see below): the pipeline is silently bypassed, so the
  backend **emulates** it in Python — min-max each leg from the per-leg scores
  (`include_named_queries_score`), then apply the same `0.7/0.3` blend. Ranking
  matches the native pipeline within ~1–2%.
- **Keyword-only** search (no embeddings available): a plain min-max of the one
  leg, since there is nothing to weight.
- **Flag absent** (older backend / website-page projection): the frontend falls
  back to its own min-max so a raw score never renders as `687%`.

The whole point of the `normalized` flag is that the frontend never has to guess
or re-scale — it reads the number and renders it.

## How ACL / DLS interacts with normalization

This is the subtle part, and it matters because **in authenticated deployments
most real users hit the emulation path, not the native pipeline.**

OpenRAG enforces document access with OpenSearch Document-Level Security (DLS).
There are two DLS roles, and they evaluate differently:

| Role | DLS clause | OpenSearch mode | Pipeline? |
|---|---|---|---|
| `openrag_user_role` | owner-based `term` on `owner` / unowned docs | **Lucene-level** | ✅ runs natively → `"pipeline"` |
| `openrag_user_acl_role` | **terms-lookup** against `openrag_dls_principals` for shared-doc access | **Filter-level** | ❌ silently bypassed → `"default"` (emulated) |

The mechanism: a DLS query that contains a **terms-lookup** forces OpenSearch
into *filter-level* evaluation. In that mode the security plugin wraps the query
and the hybrid search pipeline is **silently skipped** — no error, but hits come
back with raw, unbounded combined scores (e.g. `6.87, 4.65…` instead of
`0.7, 0.32…`). The ACL role resolves shared-document access with exactly such a
terms-lookup, so **any user mapped to the ACL role loses the pipeline.**

Without this PR, those users would have fallen back to a raw min-max of the
*combined* score — which is keyword-dominated and throws away the semantic
weighting. This PR fixes that: the hybrid query names its two legs, requests
per-leg scores via `include_named_queries_score`, and the backend reconstructs
the pipeline's exact math (`_emulate_pipeline_scores`) in the same request — no
extra round-trip. The result is that **a filter-level DLS user sees essentially
the same ranking as an admin**, instead of a degraded keyword-first ordering.

Two related hardening fixes ride along:
- **DLS bool/should fallback.** On some clusters the security plugin's
  `function_score` wrapper makes OpenSearch *reject* a top-level hybrid query
  outright. The search now retries as a `bool/should` query so DLS users still
  get keyword+semantic results instead of an error.
- **Score threshold under DLS.** The threshold is applied as a Python
  post-filter on normalized `[0,1]` scores; it is skipped on the raw-score
  fallback path so a miscalibrated cutoff can't wipe out a DLS user's results.

## Considerations for SaaS and CPD (authenticated modes)

The point above has direct production consequences for IBM-authenticated
deployments (`IBM_AUTH_ENABLED`, `OPENRAG_RUN_MODE=saas` or `on_prem`/CPD):

- **The emulation path is the production default, not an edge case.** In SaaS and
  CPD, real end users authenticate via the platform and are mapped to the ACL
  role so they can see shared documents. That means they run in **filter-level
  DLS → the pipeline is bypassed → they are served by the Python emulation.**
  The native `"pipeline"` path mostly covers admins, no-auth/dev, and owner-only
  users. So the quality of the emulation (validated to ~1–2% of the pipeline,
  identical ranking) is what the majority of authenticated traffic actually
  experiences — this is by design and is the reason the emulation exists.
- **Security setup is platform-owned in these modes.** With
  `OPENRAG_RUN_MODE=saas`/`on_prem`, `OPENRAG_SKIP_OS_SECURITY_SETUP` defaults to
  `true` — OpenRAG does not create the roles/mappings; the platform (Traefik/CPD
  or the SaaS operator) owns the security context. The DLS roles above are
  therefore an assumed contract, not something this PR provisions in those modes.
- **No-auth mode deliberately skips the ACL role.** When running without auth and
  without no-auth connectors, default users are *not* mapped to the ACL role
  (its terms-lookup is what breaks the pipeline). Those users stay on the native
  pipeline. This keeps local/OSS runs on the faster, authoritative path.
- **The weighted blend is scale-independent.** Because each leg is normalized to
  `[0,1]` before combining, the `0.7/0.3` split behaves the same whether the
  corpus is 20 documents or millions — raw BM25 magnitude no longer leaks into
  ranking. This is what makes the single-config-file tuning safe to carry from
  dev into SaaS/CPD without per-environment recalibration.
- **Follow-up to watch at scale:** the emulation normalizes over *returned* hits
  while the native pipeline normalizes over its larger internal candidate set, so
  absolute scores (not ranking) drift by ~1–2%. The gap shrinks as the result
  `limit` grows; worth monitoring if a SaaS tenant runs with very small limits.

---

## Key decisions & rationale

| Decision | Why |
|---|---|
| Use OpenSearch normalization pipeline, not manual score math | Each leg is normalized before combining, so BM25's unbounded scale stops drowning the semantic signal. The 70/30 weight finally means what it says. |
| Backend owns normalization; frontend trusts it | Kills the double-normalization that made the top result always read 100%. Percentages now carry real meaning. |
| Emulate the pipeline for filter-level DLS instead of raw min-max | DLS users bypass the pipeline; a raw min-max is keyword-dominated. Emulation gives them the same weighted ranking as everyone else, in the same request. |
| Keep weights/thresholds in one JSON file | Retuning (e.g. 0.7→0.8 semantic) is a single edit read by both stacks; no code change, applied on next startup. |
| Accept a small deep-recall dip for better top-1 ranking | Users read the top of the list. Ranking the correct answer #1 more often is worth losing an occasional deep hit — and the weights are tunable if we want to shift the balance back. |

---

## Eval results

**Run `eval-dca8387f` (this branch) vs baseline `eval-523625f6` (main).**
83 questions, 21-document corpus, fetch limit 50, threshold 0.0,
embedding `granite-embedding-278m-multilingual`.

### Aggregate change

| Metric | main | branch | Δ |
|---|---|---|---|
| recall@1 | 0.596 | 0.614 | **+0.018** |
| recall@3 | 0.825 | 0.813 | −0.012 |
| recall@5 | 0.886 | 0.880 | −0.006 |
| recall@10 | 0.952 | 0.940 | −0.012 |
| MRR | 0.770 | 0.784 | **+0.015** |
| nDCG@1 | 0.675 | 0.699 | **+0.024** |
| nDCG@5 | 0.779 | 0.789 | **+0.010** |
| nDCG@10 | 0.802 | 0.811 | **+0.009** |
| passage hit@1 | 0.494 | 0.545 | **+0.052** |
| passage hit@5 | 0.779 | 0.792 | **+0.013** |
| Passage MRR | 0.615 | 0.644 | **+0.028** |

**Question-level:** 14 improved, 11 regressed, 58 unchanged, 0 added, 0 removed.
Nearly every regression is a correct answer slipping one rank (e.g. #1 → #2),
not disappearing — a direct consequence of keyword no longer over-ranking. The
one real drop-out was `restrict-senders` (fell from rank #4 to #6, out of top 5).

### By question type (branch)

| Tag | Questions | recall@5 | MRR | passage hit@5 |
|---|---|---|---|---|
| exact-token | 13 | 1.000 | 1.000 | 1.000 |
| keyword | 7 | 0.929 | 0.833 | 1.000 |
| multi-doc | 16 | 0.812 | 0.900 | 1.000 |
| semantic | 63 | 0.849 | 0.735 | 0.724 |

Keyword and exact-token queries stay perfect. The remaining weak spot is
**semantic (paraphrase) queries** — where the right chunk is retrieved but
ranked low (e.g. answer chunk at rank #10–#50). That is a ranking/embedding
limitation, the main target for follow-up.

---

## Known trade-offs & follow-ups

- **Deep recall dipped ~1 question** at recall@5/@10 — expected cost of removing
  keyword over-ranking; recoverable by nudging the semantic weight.
- **Semantic paraphrase queries are the weak spot** (63 of 83 questions). Two
  cheap, no-reindex experiments queued: (a) sweep semantic/keyword weight
  (0.7→0.8), (b) relax the new keyword `minimum_should_match`. Bigger lever:
  upgrade the embedding model (requires reindex).
- **DLS emulation** differs from the native pipeline by ~1–2% on absolute score
  (ranking preserved) because it normalizes over returned hits vs. the pipeline's
  larger candidate set. Inherent, documented, not a bug.
