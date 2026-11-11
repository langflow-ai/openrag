# Answer reference review

Each of the 83 `expected_answer` references was written from the corpus and
checked against it question by question. Five (`key-rotate`, `sig-roll`,
`session-length`, `card-declined` and `eu-residency`) were checked against the
corpus a second time during review.

The review covered each question's expected files, numeric values and units,
required conditions and exceptions, and whether a correct paraphrase should
receive full correctness credit. References deliberately do not require the
retrieval snippet verbatim.

Particular cases checked:

- `session-length`: 12-hour overall and 60-minute idle defaults; Enterprise
  can change the overall session length. The configuration reference also
  exposes an idle timeout setting, so the reference describes defaults.
- `gone-410`: retries stop, the destination pauses, and the event enters its DLQ.
- `duplicate-events`: response loss and overlapping routes are distinct causes.
- `payload-retention-scale`: 30 days is a payload maximum, not the 90-day
  metadata retention or a guaranteed minimum.
- `never-store-field` and `strip-fields-before-delivery`: stored-copy redaction
  does not change what the endpoint receives.
- `sig-roll`: the normal dual-signature period is 72 hours; the emergency
  Expire previous secret action is an explicit exception.
- `eu-residency`: event data stays in the EU, but account information may be
  held centrally in the US.
- `card-declined`: retries occur on days 3, 5 and 7; suspension starts on day 10,
  and closure is 30 days after suspension.
- `enforce-two-step`: password users follow the workspace requirement; SSO
  users follow their identity provider's rules.

## Judge spot-checks

Before relying on the judge, compare its scores with the corpus for about ten
answers from a live run, including every answer scored 0, and record them here.
Measure the noise level with two unchanged runs (`run_eval.py compare`) before
quoting one in the README.

| Run | Question ID | Judge score | Corpus evidence | Reviewer agrees? |
|---|---|---|---|---|
| | | | | |
