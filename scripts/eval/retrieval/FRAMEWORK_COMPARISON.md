# Retrieval eval: framework comparison

Issue [#2478](https://github.com/langflow-ai/openrag/issues/2478) asked for a
dependency-light harness that catches retrieval regressions. Before settling on
the homegrown harness in this directory, we tried three alternatives,
[RAGAS](https://docs.ragas.io), [DeepEval](https://deepeval.com) and
[LangSmith](https://docs.smith.langchain.com), on the same inputs: this
directory's 21-document `corpus/` and 83-question `queries.jsonl`. We also
looked at two tools we did not build with, IBM watsonx.governance and Langfuse,
because they matter for later phases.

## How we tested

- **Offline, all three frameworks.** Each one scored the same synthetic ranked
  file lists and had to produce the three metrics this project needs:
  file-level recall@k, MRR and nDCG@k. No LLM judge was used.
- **Live, DeepEval only.** A DeepEval version of the full harness
  (`deepeval==4.2.8`) ran against a local OpenRAG stack with watsonx
  `ibm/granite-embedding-278m-multilingual` embeddings and 1000/200 chunking.
  It ingested the corpus, ran all 83 questions through `/v1/search`, and
  collected chat answers for 20 questions. See
  [Live DeepEval run](#live-deepeval-run).

The framework variants were throwaway spikes and are not part of this PR. Only
this writeup and its findings are kept.

## Summary

| | Homegrown (this directory) | RAGAS | DeepEval | LangSmith |
|---|---|---|---|---|
| Unit tests | 29 | 4 | 7 offline, 32 in the live spike | 8 |
| Tests passing | 29/29 | 4/4 | all | 8/8 |
| New packages installed | 0 (`openrag-sdk` only, already required) | 95 | 68 | 25 |
| Pulls in | nothing new | `langchain`, `langchain-community`, `langchain-openai`, `openai`, `datasets`, `pillow`, `networkx` | `openai`, `grpcio`, `posthog`, `opentelemetry-*` | its own small SDK |
| Native recall@k, MRR, nDCG@k | Yes | No, hand-written | No, hand-written | No, hand-written |
| Runs without an API key | Yes | Yes, after pinning `langchain-community` | Yes, after turning off telemetry | No |
| Fit for file-level ranked results | Built for it | Approximate: set-based text similarity, not rank-based | Poor: no ranked-result concept | Good: the evaluator signature maps cleanly |

In the live DeepEval spike, `uv.lock` resolved 72 packages, against 13 for this
harness. Both counts include `openrag-sdk` and its dependencies.

None of the three frameworks computes the ranking metrics this project needs.
Each one needed the same recall@k, MRR and nDCG@k code that already exists and
is tested in `metrics.py`. The frameworks differ only in the tooling around that
code, and each brings a cost with it.

## RAGAS

RAGAS evaluates RAG pipelines, mostly with LLM-judged metrics such as
faithfulness, answer relevancy, and context precision and recall. It also has
two metrics that need no LLM, `NonLLMContextRecall` and
`NonLLMContextPrecisionWithReference`, which we used here.

**Strengths**

- The non-LLM metrics need no API key or network call. `ragas.evaluate()` does
  not create a default LLM client when only `NonLLM*` metrics are selected.
- `EvaluationDataset.to_pandas()` gives a dataframe for further analysis.
- `NonLLMContextRecall` ran on all 83 questions (mean 0.717 on the synthetic
  fixtures), so the non-LLM path works in practice.

**Weaknesses**

- No ranking metrics. Its context metrics compare sets of strings with
  `rapidfuzz` and ignore rank. We wrote the same ranking code as the homegrown
  harness and passed the results through RAGAS for the report.
- The heaviest install: 95 packages, including the full LangChain stack, for
  scoring that uses none of it.
- `import ragas` fails with a current `langchain-community`. ragas 0.4.3
  imports `langchain_community.chat_models.vertexai.ChatVertexAI` at import
  time, and `langchain-community` 0.4 removed that module. We had to pin
  `langchain-community==0.3.27`.
- The non-LLM context metrics need `rapidfuzz`, which ragas does not install.

## DeepEval

DeepEval tests LLM output (correctness, faithfulness, relevancy) through
`LLMTestCase` and mostly LLM-judged metrics, with a pytest-style
`deepeval test run` command.

**Strengths**

- Custom deterministic metrics are clean to write. Subclassing `BaseMetric`
  (`measure()`, `a_measure()`, `is_successful()`, `__name__`) plugged straight
  into `evaluate()` and its report.
- Telemetry (PostHog) turns off with `DEEPEVAL_TELEMETRY_OPT_OUT=YES`. Nothing
  goes to Confident AI unless `CONFIDENT_API_KEY` is set. The offline 83-question
  run took about 0.2 s with no network activity.
- `FaithfulnessMetric` and `AnswerRelevancyMetric` come ready-made, with
  prompts, verdict schemas, reasons and per-metric cost. This is the main reason
  to consider DeepEval for answer quality.
- `assert_test` with `deepeval test run` works as a CI gate with readable
  failure messages.

**Weaknesses**

- No concept of a ranked result set or a set of expected documents.
  `LLMTestCase` models one LLM input and output. Expected files had to go
  through `metadata` or be packed into `expected_output` as a string. DeepEval
  does no deduplication or ranking itself, so all of that is still custom code
  that duplicates `metrics.py`.
- 68 packages, including a hard dependency on `openai`, plus `grpcio` and
  `opentelemetry-*`, for scoring that is plain arithmetic.
- Built-in metrics need an LLM client even to be constructed. With no key,
  `GPTModel` raises at construction.
- `evaluate()` prints Confident AI banners and writes a `.deepeval/` directory
  in the current directory.
- Fast-moving API. Three releases (4.2.9 to 4.3.1) came out in the five days
  before our run, and recent releases added new evaluation modes.

### Live DeepEval run

The spike ran the full retrieval eval twice against the local stack (83
questions, fetch limit 50):

| Run | recall@5 | MRR | nDCG@5 |
|---|---|---|---|
| Homegrown baseline (earlier stack state) | 0.904 | 0.809 | 0.808 |
| DeepEval run 1 | 0.940 | 0.806 | 0.822 |
| DeepEval run 2 | 0.928 | 0.836 | 0.840 |

- **Same scores as this harness.** We re-scored every ranking from DeepEval
  run 1 with this directory's `metrics.score_query`. All 83 questions matched.
  The gap to the older baseline comes from the stack returning different
  rankings, not from scoring. A homegrown run three days after the baseline
  had already measured 0.928 / 0.814 / 0.823.
- **Same noise.** 11 of 83 questions moved between the two unchanged runs, and
  recall@5 moved by 0.012, about a third of a 0.03 gate margin. This matches
  what the [README](README.md#repeatability) describes for this harness.
- **Chat scoping works.** All 20 chat answers came back. Every source cited
  (200 of 200) was one of the run's own files, so filters passed to
  `/api/v1/chat` are honored.
- **Answer quality was not scored.** No judge key was available, so faithfulness
  and answer relevancy were not measured. Measured from the real prompts, a
  gpt-4.1-mini judge would make about 140 calls and cost about $0.07 to $0.15
  per 20-question run.
- **Size.** About 1,355 lines of code, including tests and the answer-quality
  commands. The ranking logic was still custom code, not DeepEval's.

DeepEval reproduced this harness's numbers exactly, but it added no retrieval
capability. Everything it measured, this harness already measures.

## LangSmith

LangSmith is a hosted service for experiment tracking and evaluation, with
LLM-judged or custom code evaluators.

**Strengths**

- The lightest install of the three: 25 packages, about 33 MB, with no
  `langchain` or `openai`.
- The code-evaluator signature,
  `(inputs, outputs, reference_outputs) -> {"key", "score"}`, fits file-level
  ranked results without workarounds.
- With a hosted account, it would provide experiment-to-experiment diffs in a
  shared UI, per-example traces, dataset versioning and shareable experiment
  links.

**Weaknesses**

- It does not work without a hosted account. `Client()` constructs without a
  key, but `client.create_dataset(...)` fails with
  `401 LangSmithAuthError: Invalid token`. `client.evaluate(...,
  upload_results=False)` fails with the same error, because it looks the dataset
  up on the hosted API before running. There is no offline mode, and every
  headline feature needs the account.
- Calling the evaluator functions directly reproduces the scores, but that is
  plain Python, not LangSmith. Run-to-run comparison, its main draw for us, is
  already covered by `report.py`.

## Tools we did not build with

### IBM watsonx.governance

IBM's evaluation SDK (`ibm-watsonx-gov`, version 1.5.2 checked) is the closest
match to how IBM evaluates RAG elsewhere, so it is the main candidate for
phase 3.

- **It has retrieval metrics.** Unlike the three frameworks above, it lists
  hit rate, reciprocal rank, average precision, NDCG, retrieval precision and
  context relevance, run through `MetricsEvaluator`. As documented, these are
  computed from per-chunk relevance scores produced by a judge, not from
  labeled expected files, so they answer a different question from this
  harness. Confirm this before relying on them.
- **It has answer metrics:** faithfulness, answer relevance and answer
  similarity.
- **Costs:** a proprietary IBM license, an IBM Cloud API key for every run, and
  a judge model call per metric. It cannot run in CI without credentials.

This harness's results files could be passed to it in phase 3 without changing
the retrieval side.

### Langfuse

OpenRAG already sends traces to Langfuse when the `LANGFUSE_*` variables are
set. Langfuse is open source, can be self-hosted, and has datasets and
experiments with a UI. The issue lists it, with Arize Phoenix and Braintrust,
for the customer-facing phase. It does not compute ranking metrics either, but
it could store and display this harness's results without a new vendor.

## Why we chose the homegrown harness

1. **It is the only option with the metrics the issue asks for.** RAGAS,
   DeepEval and LangSmith all needed recall@k, MRR and nDCG@k written by hand,
   which is the code already in `metrics.py`. watsonx.governance's ranking
   metrics are judged rather than label-based, need an IBM Cloud key, and fit
   phase 3 rather than phase 1.
2. **No new dependencies.** It needs only `openrag-sdk`, which the project
   already has. RAGAS adds 95 packages, DeepEval 68 and LangSmith 25, and the
   issue asks for something dependency-light.
3. **It produces the same numbers.** The live DeepEval run matched this
   harness's scores on all 83 questions, so switching would add size without
   changing a result.
4. **Its data model fits.** `Query`, `RankedFile` and `score_query()` model
   file-level ranked scoring with an optional text check. Each framework needed
   a workaround: expected files packed into strings, no ranked-result concept,
   or no offline mode.
5. **No account, key or network service.** This matters for running in CI in
   phase 2. LangSmith cannot run without a hosted account, and RAGAS and
   DeepEval avoid one only through careful metric choice and opt-out settings
   that are off by default.
6. **The reporting is already there.** `report.py` writes JSON results, a
   Markdown summary and a question-by-question baseline diff, which covers what
   the frameworks' reports offer without a hosted dashboard.

## Where the other tools fit later

The issue's phases:

- **Phase 3, answer quality:** DeepEval, RAGAS and watsonx.governance are the
  candidates, since LLM-judged answer metrics are what they are built for.
  watsonx.governance fits IBM's existing evaluation practice. DeepEval had the
  smoothest path in our spike.
- **Phase 4, customer-facing reports:** Langfuse is already integrated with
  OpenRAG. LangSmith is worth revisiting only if a hosted account becomes part
  of the plan.
