# Retrieval eval: framework comparison

Issue [#2478](https://github.com/langflow-ai/openrag/issues/2478) asked for a
dependency-light harness to catch retrieval regressions. Before settling on
the homegrown harness in this directory, we built out three alternatives —
[RAGAS](https://docs.ragas.io), [DeepEval](https://deepeval.com), and
[LangSmith](https://docs.smith.langchain.com) — against the exact same inputs
(this directory's 21-document `corpus/` and 83-question `queries.jsonl`) to
get a real, apples-to-apples comparison instead of deciding from docs alone.

**Scope of the test.** Each variant scored the same synthetic ranked-filename
fixtures (no live OpenRAG stack was available while this comparison ran) and
had to produce the same three metrics this project needs: file-level
**recall@k**, **MRR**, and **nDCG@k**. No LLM judge was used or available for
any framework — every comparison below is on deterministic, non-LLM scoring
only. All three framework variants live in local-only throwaway worktrees and
were not committed; only this writeup and its findings are kept.

## Summary

| | Homegrown (this directory) | RAGAS | DeepEval | LangSmith |
|---|---|---|---|---|
| Unit tests written | 29 (already existed) | 4 | 7 | 8 |
| Tests passing | 29/29 | 4/4 | 7/7 | 8/8 |
| New dependencies installed | **0** (`openrag-sdk` only, already required) | **95 packages** | **68 packages** | **25 packages** |
| Pulls in | nothing new | full `langchain` stack, `langchain-community`, `langchain-openai`, `openai`, `datasets`, `pillow`, `networkx` | `openai`, `grpcio`, `posthog`, `opentelemetry-*` | nothing beyond its own small SDK |
| Native recall@k / MRR / nDCG@k | ✅ built, exactly this | ❌ none — hand-written | ❌ none — hand-written | ❌ none — hand-written |
| Runs with zero API key | ✅ always | ✅ (after a required pin) | ✅ (after disabling telemetry) | ⚠️ **no** — see below |
| Schema fit for file-level IR data | Perfect — built for exactly this | Workable but approximate (text-similarity based, not rank-based) | Poor — no ranked-result concept | Good — evaluator signature maps cleanly |

**Bottom line:** none of the three frameworks have the ranking metrics this
project actually needs. All three required hand-writing the same
recall@k/MRR/nDCG@k logic that already exists, is already tested, and is
already live in this directory. The frameworks only compete on the tooling
*around* that math — and each has a real cost attached to that tooling.

## RAGAS

**What it's for:** RAG pipeline evaluation, mostly via LLM-judged metrics
(faithfulness, answer relevancy, context precision/recall as judged by an
LLM). It does have two non-LLM metrics, `NonLLMContextRecall` and
`NonLLMContextPrecisionWithReference`, which we used here.

**Strengths**
- The non-LLM metrics genuinely require no API key and no network call — we
  confirmed `ragas.evaluate()` never tries to construct a default LLM client
  as long as only `NonLLM*`-prefixed metrics are selected.
- `EvaluationDataset` / `.to_pandas()` gives a ready-made dataframe for
  further analysis once scores exist.
- Its non-LLM metric ran successfully end-to-end on our 83 queries
  (`NonLLMContextRecall` mean 0.717 on synthetic fixtures), confirming the
  non-LLM path is real and usable, not just a documented promise.

**Weaknesses**
- **No ranking metrics at all.** Nothing in RAGAS's metric catalog computes
  recall@k, MRR, or nDCG@k — its context metrics are set-based string
  similarity (via `rapidfuzz`), not rank-aware. We had to write the exact
  same ranking math as the homegrown harness and just route it past RAGAS
  for the report.
- **Heaviest install by a wide margin: 95 packages.** `pip install ragas`
  pulls in the full `langchain` / `langchain-core` / `langchain-community` /
  `langchain-openai` stack, `openai`, `datasets`, `pillow`, and `networkx` —
  all for scoring that needs none of them.
- **A real import-time landmine:** ragas 0.4.3 unconditionally imports
  `langchain_community.chat_models.vertexai.ChatVertexAI` at import time.
  `langchain-community>=0.4` dropped that module, so a plain
  `pip install ragas` combined with a newer `langchain-community` breaks
  `import ragas` outright with no non-LLM metric ever touched. We had to pin
  `langchain-community==0.3.27` to get `import ragas` working at all.
- `rapidfuzz` (needed by the non-LLM context metrics) is not pulled in by
  ragas's own dependencies and has to be added separately.

## DeepEval

**What it's for:** LLM output testing — correctness, faithfulness, relevancy
— via `LLMTestCase` and mostly LLM-judged metrics, with pytest-style
`deepeval test run` CLI integration.

**Strengths**
- The `BaseMetric` escape hatch for fully custom, deterministic metrics is
  genuinely clean — implementing `measure()` / `a_measure()` /
  `is_successful()` / `__name__` was straightforward and plugged directly
  into `evaluate()`'s console/CLI report with no LLM scaffolding leaking in.
- Telemetry (PostHog) is easy to disable (`DEEPEVAL_TELEMETRY_OPT_OUT=YES`),
  and Confident AI cloud reporting stayed inert simply by never setting
  `CONFIDENT_API_KEY` — the full 83-query run completed in ~0.2s with zero
  network activity.
- `evaluate()`'s pass/fail report (59 passed / 24 failed on our 70/30
  synthetic fixture split) is a usable CLI report "for free" once the custom
  metric exists.

**Weaknesses**
- **No native concept of a ranked result set or an expected-document set.**
  `LLMTestCase` is built around single-turn LLM input/output/context.
  `expected_files` had to be packed into `expected_output` as a
  comma-joined string and parsed back out — a workaround for a schema that
  assumes `expected_output` is prose to diff against a generated answer.
  `retrieval_context` fits reasonably (it's documented as "the retrieved
  context" and takes a plain string list), but rank is just list position —
  DeepEval does no first-occurrence dedup or ranking math itself; all of
  that is still 100% custom code duplicating this directory's `metrics.py`.
- **68 packages installed**, including a hard dependency on `openai` (per
  DeepEval's own package metadata, not anything our code imports), plus
  `grpcio` and the full `opentelemetry-*` stack — all for scoring that is
  pure arithmetic.
- `actual_output` is a required-feeling field on every `LLMTestCase` even
  though pure retrieval scoring has no generated answer to put there.

## LangSmith

**What it's for:** hosted experiment tracking and evaluation, with support
for either LLM-judged or fully custom ("code") evaluators.

**Strengths**
- **Lightest install of the three: 25 packages, ~33 MB, installed in
  12ms.** No `langchain`, no `openai` pulled in by default.
- The documented code-evaluator signature,
  `(inputs, outputs, reference_outputs) -> {"key", "score"}`, maps onto our
  file-level IR data more naturally than either RAGAS's or DeepEval's
  schemas — no string-packing workarounds needed.
- If a hosted account existed, the payoff would be real: automatic
  experiment-to-experiment diffing in a shared UI, per-example trace
  click-through, dataset versioning, and shareable experiment URLs — most of
  what a bigger team would eventually want from a reporting layer.

**Weaknesses**
- **Does not work at all without a paid/hosted account, and this was
  confirmed directly, not assumed.** `Client()` constructs without an API
  key (it's lazy), but `client.create_dataset(...)` fails immediately with
  `401 LangSmithAuthError: Invalid token`. Critically,
  `client.evaluate(..., upload_results=False)` **also** fails with the same
  401 — it still resolves the dataset against the hosted API before running
  anything, regardless of `upload_results`. **There is no offline mode.**
  Every one of its headline features (experiment diffing, trace
  click-through, dataset versioning, shareable URLs, annotation queues) is
  gated behind that same account we don't have.
- Falling back to calling the evaluator functions directly (bypassing
  `langsmith` entirely) reproduces the scoring math exactly, but at that
  point you're not using LangSmith at all — you're using plain Python with
  an evaluator-shaped function signature. The homegrown harness's own
  `report.py` (JSON + Markdown summary + baseline diff) already covers the
  one feature — run-to-run regression comparison — that would otherwise be
  LangSmith's main draw.

## Why we went with the homegrown harness

1. **It's the only one with the actual metrics the issue asked for.** All
   three frameworks required hand-writing recall@k, MRR, and nDCG@k from
   scratch — the exact same code that already exists, tested, and working in
   `metrics.py`. None of their "retrieval" metrics are rank-aware.
2. **Zero new dependencies, by a wide margin.** The homegrown harness adds
   nothing beyond `openrag-sdk` (already a project dependency). RAGAS adds
   95 packages, DeepEval 68, LangSmith 25 — and the issue explicitly asked
   for something dependency-light.
3. **The schema is a perfect fit because it was built for this.** `Query`,
   `RankedFile`, and `score_query()` model exactly file-level IR scoring with
   an optional snippet gate. Every framework we tried required a workaround
   (string-packed expected answers, no ranked-result concept, or no offline
   mode at all) because they're built for LLM-output evaluation, not pure
   search-quality scoring.
4. **No account, no API key, no network dependency, ever.** This matters
   doubly for a harness meant to run in CI later (phase 2): LangSmith simply
   cannot run without a hosted account, and RAGAS/DeepEval only avoid needing
   one by careful selection of non-LLM metrics plus environment-variable
   opt-outs that aren't on by default.
5. **We already get the reporting we need.** `report.py`'s JSON output,
   Markdown summary, and baseline-diff mode (regressions/improvements per
   query, not just an aggregate) match or exceed what any of the three
   frameworks give "for free" in their reports — without needing a hosted
   dashboard.

**Where these frameworks would earn their place later**, per the issue's own
phased plan: RAGAS and DeepEval are strong candidates for **phase 3** (an
LLM-judged answer-quality layer — that's what their flagship metrics are
actually designed for), and LangSmith is worth revisiting for **phase 4**
(customer-facing hosted reporting), once a hosted account is actually part of
the plan.
