# Retrieval evaluation harness

This harness measures how well OpenRAG search finds the right documents. It
ingests a fixed set of documents, sends a fixed set of labeled questions
through the public search API (`/v1/search`), and scores where the expected
documents land in the results. Run it before and after a change to search,
chunking or embeddings to see which questions got better and which got worse.

It measures retrieval only. It does not judge chat answers.

[FRAMEWORK_COMPARISON.md](FRAMEWORK_COMPARISON.md) explains why this harness is
homegrown rather than built on RAGAS, DeepEval or LangSmith.

## Quick start

Run these from this directory against a running stack. You need an API key
from **Settings → API Keys**.

```bash
cd scripts/eval/retrieval
export OPENRAG_URL=http://localhost:3000
export OPENRAG_API_KEY=orag_your_api_key

# Check the corpus and questions. Needs no stack.
uv run run_eval.py run --validate-only

# Run every question and keep the results as a baseline.
uv run run_eval.py run
cp results/results.json results/baseline.json

# After a change to search, chunking or embeddings, run again and compare.
uv run run_eval.py run --baseline results/baseline.json

# Read the summary of the latest run.
cat results/summary.md
```

The same steps are available as `make` targets from the repository root.
Paths are relative to this directory.

| `make` target | Same as |
|---|---|
| `make eval-validate` | `uv run run_eval.py run --validate-only` |
| `make eval-run` | `uv run run_eval.py run` |
| `make eval-run BASELINE=results/baseline.json` | `uv run run_eval.py run --baseline results/baseline.json` |
| `make eval-baseline` | `uv run run_eval.py run`, then copy the results to `results/baseline.json` |
| `make eval-compare` | `uv run run_eval.py compare results/baseline.json results/results.json` |
| `make eval-compare BASELINE=a.json CURRENT=b.json` | `uv run run_eval.py compare a.json b.json` |
| `make eval-baseline OUTPUT_DIR=results/demo` | `uv run run_eval.py run --output-dir results/demo`, then copy the results to `results/demo/baseline.json` |

Pass any other option with `EVAL_ARGS`, for example
`make eval-run EVAL_ARGS="--keep-documents --fetch-limit 100"`. To write results
somewhere else, set `OUTPUT_DIR` rather than passing `--output-dir` in
`EVAL_ARGS`, so `eval-baseline` copies the file the run actually wrote.
`make eval-baseline` stops with an error if `EVAL_ARGS` contains `--output-dir`.

The rest of this file explains each step.

## What is here

| Path | Purpose |
|---|---|
| `corpus/` | 21 Markdown documents: the handbook of a fictional product, "Relaywise" |
| `queries.jsonl` | 83 hand-labeled questions, one JSON object per line |
| `run_eval.py` | The command-line tool, with `run` and `compare` commands |
| `dataset.py` | Loads and validates the corpus and questions |
| `metrics.py` | Turns ranked chunks into ranked files and scores them |
| `report.py` | Writes results, the summary and the baseline diff |
| `FRAMEWORK_COMPARISON.md` | How this harness compares with RAGAS, DeepEval, LangSmith and others |
| `results/` | Output of each run (not committed) |

The corpus is invented so that no model has seen it and no license applies. Its
documents overlap on purpose. For example, API keys and signing secrets both
have a "rotation" section, so the ranking has to tell them apart.

## Prerequisites

- A running OpenRAG stack that has finished onboarding, with working ingestion
  and an embedding model.
- Python 3.11 or later and [uv](https://docs.astral.sh/uv/).
- An OpenRAG API key. When RBAC is enforced (`OPENRAG_RBAC_ENFORCE=true`), the
  key needs these permissions:

  | Permission | Used for |
  |---|---|
  | `knowledge:upload` | Ingesting the corpus |
  | `knowledge:read:own` | Reading ingestion task status |
  | `search:use` | Running the questions |
  | `knowledge:delete:own` | Deleting the corpus when the run ends |
  | `providers:read` | Recording the embedding and chunk settings (optional) |

The harness depends only on `openrag-sdk`, which it takes from `sdks/python` in
this checkout, so a run tests the SDK and API of the code you have checked out.

## Run it

```bash
cd scripts/eval/retrieval
export OPENRAG_URL=http://localhost:3000
export OPENRAG_API_KEY=orag_your_api_key

uv run run_eval.py run
```

A run does the following:

1. Validates the corpus and the question file. A bad label stops the run
   before anything is uploaded.
2. Uploads each corpus file under a name unique to the run, such as
   `eval-3f9a12cd-api-keys.md`, and waits until every file is searchable.
3. Sends each question to `/v1/search`, limited to the files this run uploaded,
   so other documents in the stack are never returned. They can still shift
   the scores slightly; see [Repeatability](#repeatability).
4. Prints a summary and writes it, with the full results, to `results/`.
5. Deletes the files it uploaded.

Documents that were already in the stack are never searched, changed or
deleted. If a run is interrupted before cleanup, delete the leftover
`eval-<run id>-*` files from the knowledge page.

Useful options:

| Option | Default | Purpose |
|---|---|---|
| `--baseline FILE` | none | Compare this run with an earlier results file |
| `--output-dir DIR` | `results/` | Where to write results |
| `--k 1,3,5,10` | `1,3,5,10` | Cutoffs to report |
| `--fetch-limit N` | `50` | Chunks requested per question; must be at least the largest `--k` |
| `--score-threshold X` | `0` | Minimum score passed to search |
| `--concurrency N` | `4` | Parallel uploads |
| `--keep-documents` | off | Leave the uploaded files in place for debugging |
| `--validate-only` | off | Check the dataset and exit; needs no stack |

Run `uv run run_eval.py run --help` for the full list, including timeouts.

## Compare before and after a change

```bash
# 1. On main, or before your change:
uv run run_eval.py run
cp results/results.json results/baseline.json

# 2. Apply the change, restart the stack, then:
uv run run_eval.py run --baseline results/baseline.json
```

The summary then ends with a comparison that lists the questions that
regressed first, then the ones that improved, then the change in each average.
For every changed question it shows the rank of each expected file before and
after.

To make a run exit with status 1 when average recall falls too far, add
`--max-recall-drop 0.02` (two points) next to `--baseline`. It is off by default.

To compare two results files without running anything:

```bash
uv run run_eval.py compare results/baseline.json results/results.json
```

The comparison warns when the two runs differ in something other than the
change under test: the corpus, the question file, the k values, the fetch
limit, the score threshold, or the embedding and chunk settings of the stack.
Scores from different embedding models or chunk sizes are not comparable unless
that setting is what you are testing.

### Repeatability

Two runs against the same stack do not give exactly the same scores. Search
combines vector similarity with keyword matching, and the keyword part weighs
each word by how common it is across the whole index. That count includes
documents outside the eval, and chunks that earlier runs deleted but OpenSearch
has not yet purged. Each run therefore changes the index a little for the next.

On a local stack with watsonx embeddings, three unchanged runs in a row gave
the same recall@5 (0.904) and an MRR within 0.002, but up to 13 of the 83
questions moved by one rank and were listed as regressed or improved. Halving
the chunk size moved recall@5 by 0.036 and MRR by 0.070.

To tell a real change from this noise:

- Run the baseline twice and compare the two runs. Whatever that comparison
  lists is the noise level of your stack.
- Trust the averages and changes in recall@5 over a one-rank move on a single
  question.
- For the steadiest numbers, use a stack that holds no other documents.

No baseline is committed. Scores depend on the embedding model and settings of
the stack that produced them, so create the baseline on the same stack you test
against.

## Run it from GitHub Actions

The **Retrieval Eval** workflow ([`eval-retrieval.yml`](../../../.github/workflows/eval-retrieval.yml))
runs the harness on a fresh stack built from the branch you pick and compares
it with the tracked [`baseline.json`](baseline.json). It runs only when someone
starts it. It never runs on a push or a pull request, and it is not a required
check.

To start it, open the **Actions** tab, choose **Retrieval Eval**, click **Run
workflow**, pick a branch and fill in the inputs. Or from the command line:

```bash
gh workflow run eval-retrieval.yml --ref my-branch
```

GitHub lists a manually started workflow only once its file is on the default
branch, so this works after the workflow has been merged.

| Input | Meaning |
|---|---|
| `max_recall_drop` | Fail the run if average recall at the compared cutoff falls by more than this below the baseline, for example `0.02` for two points. Leave it empty to report without failing. |
| `update_baseline` | If the run improves on the baseline, commit the new `baseline.json` to the selected branch. Refused on the default branch. |
| `min_gain` | Average recall must rise by more than this to count as an improvement. Default `0.01`, so run-to-run noise does not raise the baseline. |

Each run writes the summary to the run's page and uploads `results.json` and
`summary.md` as the `retrieval-eval-results` artifact, kept for 90 days.

### The tracked baseline

`baseline.json` is committed to the repository and is the reference for every
run. It changes only through `update_baseline`:

1. Run the workflow on your branch with `update_baseline` ticked.
2. If average recall rose by more than `min_gain`, the workflow commits the new
   `baseline.json` to your branch. Otherwise it leaves the file alone and says
   why in the run summary.
3. Merge the branch in a pull request. The reviewer sees the new scores in the
   diff.

The workflow never commits to the default branch, so a baseline change is
always reviewed. A run is not promoted when it is not like for like with the
baseline (a different corpus, question file, cutoffs or stack settings),
because a higher number would not mean better search. To start over after such
a change, for example a new embedding model, delete `baseline.json` and run
with `update_baseline`. With no baseline, the first run becomes the baseline.

The same logic is available locally:

```bash
uv run run_eval.py promote results/results.json baseline.json --min-gain 0.01
```

It exits with 0 when it wrote the baseline and 3 when it left it alone.

The stack uses the embedding provider and model set by the repository's
`EMBEDDING_PROVIDER` and `EMBEDDING_MODEL` secrets, the same as the end-to-end
tests. Scores from different models are not comparable, and the comparison
warns when the settings of the two runs differ.

The harness gives the same stack slightly different scores from run to run (see
[Repeatability](#repeatability)). Set `max_recall_drop` and `min_gain` above that
noise, or runs will fail, or the baseline will creep up, on unchanged code.

## How questions are scored

Search returns chunks, but questions are labeled with files, because chunk
boundaries move whenever chunking changes. For each question the harness:

1. Requests `--fetch-limit` chunks.
2. Keeps the first chunk of each file, which gives a ranked list of unique
   files.
3. Treats an expected file as relevant if it is in that list. If the question
   has an `expected_text`, at least one returned chunk of that file must also
   contain the text. The match ignores case and differences in whitespace.

| Metric | Meaning |
|---|---|
| recall@k | Share of the expected files that appear in the top k files |
| MRR | 1 divided by the rank of the first relevant file, averaged over questions; 0 when none is returned |
| nDCG@k | Like recall@k, but a relevant file counts for more the nearer it is to the top |

All three run from 0 to 1, and higher is better. Runs are compared on recall@5.
If either run did not evaluate k=5, the comparison uses a cutoff both runs have
and says so. Two runs with no cutoff in common cannot be compared.

## Results files

Each run writes four files to the output directory: `results.json` and
`summary.md` for the latest run, and a timestamped copy of each.

`results.json` has these parts:

| Field | Contents |
|---|---|
| `schema_version` | Format version of the file |
| `run` | Run ID, time, target URL, SDK version, git commit, hashes of the corpus and question file, k values, fetch limit and score threshold |
| `settings` | Embedding provider and model, chunk size and overlap, as reported by the stack; `null` if they could not be read |
| `metrics.overall` | Mean of each metric over all questions |
| `metrics.by_tag` | The same means for each tag, with the number of questions |
| `queries` | One record per question |

Each record in `queries` holds the question, its labels, the ranked files with
the score of their first chunk, the rank of each expected file
(`expected_ranks`, `null` when a file was not returned), whether the expected
text was found, and the metrics for that question.

## Add or change a question

Add a line to `queries.jsonl`:

```json
{"id": "key-rotate", "query": "How do I swap out an API key without causing downtime?", "expected_files": ["api-keys.md"], "expected_text": "overlap window", "tags": ["semantic"]}
```

| Field | Required | Meaning |
|---|---|---|
| `query` | Yes | The question, as a user would type it |
| `expected_files` | Yes | Corpus filenames that answer it; list more than one only if each file answers it |
| `id` | No | Stable name used to match the question between runs; defaults to the query text |
| `expected_text` | No | A short phrase that appears in every expected file |
| `tags` | No | Labels used to break the scores down |

Guidelines:

- Write the question in your own words. A question copied from the document
  mostly tests keyword matching.
- Give every question an `id`. Without one, rewording the question makes it
  look like one question was removed and another added.
- Keep `expected_text` to a few words from a single line of body text, not a
  heading. A long phrase can be split across two chunks and then never match.
- Use the existing tags where they fit: `semantic` for a paraphrased question,
  `keyword` for one that uses the document's own terms, `exact-token` for an
  identifier such as an error code or a setting name, and `multi-doc` when more
  than one file is expected.

To add a document, put a Markdown file in `corpus/` and add at least one
question that expects it.

Then check the dataset. This needs no stack:

```bash
uv run run_eval.py run --validate-only
```

Changing the corpus or the questions changes the scores, so create a new
baseline afterwards. The comparison warns if you forget.

## Tests

The scoring, validation and comparison logic is covered by
`tests/unit/test_retrieval_eval.py`, which needs neither the SDK nor a stack.
From the repository root:

```bash
uv run pytest tests/unit/test_retrieval_eval.py
```
