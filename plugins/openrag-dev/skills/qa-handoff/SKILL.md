---
name: openrag_dev_qa_handoff
description: Generate a QA handoff message summarizing every commit merged into a release branch within a date range, including the branch's latest SHA, each commit's PR link, a plain-English fix summary, and concrete test steps. Use when the user asks to prepare a QA handoff, release handoff, or "what changed" summary for a branch.
---

Generate a QA handoff message for a release branch: a scannable, per-commit breakdown of what changed, who can review the PR, and how QA should verify it.

## Step 1: Gather inputs

- **Release branch**: if not given, ask for it. If the user is working inside a git repository and doesn't name a branch, offer the current branch as a candidate but confirm before using it.
- **Date range**: ask "How many days back should I look?" and offer **last 24 hours as the default** if the user gives no answer. Also accept, if the user states it directly:
  - a number of days ("last 3 days") → range = now minus N days, through now
  - an explicit start date, optionally with an end date ("from July 10th", "from July 10 to July 12") → use exactly as given
- If the range was inferred from a default or a vague answer, state the resolved range back to the user in one line before proceeding (e.g. "Looking at commits on `release-1.52` from 2026-07-12 09:00 to 2026-07-13 09:00."). Skip this confirmation if the user already gave explicit dates.

## Step 2: Resolve the branch and its latest commit

- Make sure the branch ref is current (fetch it if working from a local clone).
- Get the latest commit SHA on that branch.
- Determine the repository's owner/name from its remote URL — needed to construct PR links.

## Step 3: List commits in range

- List every commit reachable on the branch whose commit date falls within the resolved date range.
- Order newest first.
- If no commits fall in the range, say so plainly and stop. Do not fabricate commits or invent a handoff for an empty range.

## Step 4: Enrich each commit

For every commit in range, gather:

1. **Full commit message** (subject + body) — the body sometimes has more context than the subject line alone.
2. **PR number**: most commits on this project are squash-merged and end with a trailing `(#1234)` in the subject. Extract it with a regex. Some backport commits carry two numbers (e.g. `(#1587) (#2008)`) — when that happens, use the **last** number, since that's the PR that actually merged the commit into this branch. If no number appears in the message, search for a merged pull request associated with that commit SHA instead of guessing.
3. **PR link**: build it from the repo owner/name resolved in Step 2 and the PR number, in the form `https://github.com/<owner>/<repo>/pull/<number>`.
4. **PR testing notes**: fetch the pull request's description/body and look for any existing "Test plan", "Testing", or "How to test" section — reuse it rather than reinventing test steps the author already wrote.
5. **Diff**: inspect the commit's changed files and the actual diff content. This is the source of truth for what to write in "Fixed", "what to test", and "how to test" — never write a claim the diff doesn't support.
6. **Compose**, grounded in 1–5 above:
   - **One-liner**: a plain-English restatement of the commit subject, with any conventional-commit prefix (`fix:`, `feat:`, `refactor:`, …) and trailing PR reference stripped. Rewrite terse subjects into something a non-author can understand.
   - **Fixed**: 1–2 sentences on the actual bug or behavior addressed. Pull from the commit body or PR body if either has more detail than the subject; otherwise infer precisely from the diff.
   - **What to test**: bullet list of the feature areas or user flows the diff touches.
   - **How to test**: bullet list of concrete, actionable steps (setup → action → expected result). Prefer the PR's own testing notes when present; otherwise derive steps directly from the diff — never write a step disconnected from what actually changed.

## Step 5: Render

Fill in the standard template in `TEMPLATE.md` (bundled alongside this file) with the gathered header fields and one commit section per commit, newest first. Use that template's exact structure every time — don't freehand a different layout.

## Step 6: Deliver

- Post the rendered handoff message in the conversation.
- Offer — don't assume — to save it to a file such as `qa-handoff-<branch>-<date>.md` if the user wants a persistent copy.

## Edge cases

- **No PR found for a commit**: state "No PR found" in that commit's PR field rather than guessing a link.
- **No way to look up merged PRs by commit SHA**: fall back to regex-extracted PR numbers only, and note in the handoff that PR-body testing notes could not be checked for commits without an explicit `(#N)` reference.
- **Diff too large to read in full**: summarize from the file-level change list (which files, what kind of change) rather than skipping the commit or inventing detail.
- Never fabricate test steps, PR links, or fix descriptions that aren't grounded in the commit's actual message, diff, or PR body.
