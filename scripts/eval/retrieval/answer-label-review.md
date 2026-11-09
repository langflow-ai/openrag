# Answer reference review

All 83 references were drafted and checked against the corpus during implementation.
This is an agent review, not a completed human sign-off. Human review of the
references and live judge spot-checks remain required before the PR is ready.
No PR has been published.

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

For live review, retain a table of question ID, judge score, corpus evidence,
and reviewer agreement. Include every score-0 answer and enough other answers
to reach approximately ten. Record two unchanged runs and their aggregate
score deltas before documenting a measured noise level.
