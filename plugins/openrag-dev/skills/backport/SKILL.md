---
name: openrag_dev_backport
description: Backport commits/PRs present on a source branch but missing from a target branch (e.g. a release branch into main). Cherry-picks each missing commit, skips commits already present under a different SHA, resolves cross-commit ordering, resolves merge conflicts, verifies with tests/typecheck, and opens one PR per backported commit against the target branch. Use when the user asks to backport, forward-port, or bring one branch's changes into another. Inputs — source branch and target branch, e.g. release-saas-ga-0.6.2 into main.
---

Backport every commit that exists on a source branch but is missing from a target branch: one clean PR per commit, correctly ordered, conflicts resolved and verified rather than guessed.

## Step 1: Gather inputs

- **Source branch** and **target branch**: if either is missing, ask for both. Example: source `release-saas-ga-0.6.2`, target `main`.
- Confirm the repo/remote (`git remote -v` or the current directory's origin) rather than assuming.
- Do the work in an isolated git worktree tracking the target branch, not the user's current checkout — never disturb a working tree that might hold the user's own in-progress (possibly uncommitted) work.

## Step 2: List candidate commits

- Fetch both branches, then list commits reachable on source but not target: `git log <target>..<source> --oneline`.
- Resolve each commit to a PR number: most commits on this project are squash-merged and end with a trailing `(#1234)` in the subject. Some backport-of-backport commits carry two numbers (e.g. `(#2016) (#2021)`) — use the **last** number, since that's the PR that actually merged the commit into the source branch. If no number appears, look up a merged PR associated with that commit SHA instead of guessing.

## Step 3: Filter out false positives

A commit can show up in Step 2's list yet already be effectively present on target under a *different* SHA — e.g. the original PR was merged straight to target, and only later cherry-picked into source under a new PR number (or vice versa: something merged into target already carries the same change as an older source commit).

- Cross-check: does target's log already contain a commit referencing the same PR number, or a matching title/keywords?
- The decisive test: attempt the cherry-pick (Step 5). An **empty cherry-pick result means the change is already applied** — skip it, record it as already-present, and move on. Don't trust title-matching alone; verify with the empty-diff test before ruling a commit out.

## Step 4: Determine ordering and dependencies

- List the files each remaining candidate commit touches.
- Commits that touch overlapping files must be applied in the **same chronological order they were originally merged on the source branch**, each one's backport branch stacked on top of the previous dependency's backport branch — not directly on target. This reproduces the exact context the commit was originally written against and avoids spurious conflicts that have nothing to do with the real change.
- Commits with no file overlap with anything else in the candidate set branch directly off target and can be done in any order / in parallel.

## Step 5: Apply each commit

Work through the candidates in dependency order from Step 4. For each:

1. Create a branch (naming: `backport/<PR#>-<short-desc>`) off target, or off the predecessor's backport branch if it's part of a dependency chain.
2. Cherry-pick the commit.
   - **Empty result** → already present on target (Step 3 confirmed this can happen) — delete the branch, record it as skipped, move to the next commit.
   - **Clean pick** → continue to verification.
   - **Conflict** → inspect every conflicted hunk before resolving anything. Two distinct situations look similar but need different fixes:
     - *Additive conflict against an unrelated feature already independently on target* (target evolved on its own since source and this commit diverged): usually both sides' changes are wanted together. Confirm any field/parameter one side references is actually in scope on the other side (e.g. read the surrounding function signature or dataclass) before assuming "keep both" is correct — don't paste both blocks blindly.
     - *Ordering conflict against another commit still waiting to be backported*: this means Step 4's dependency chain was wrong or incomplete — fix the chain (stack this branch on the right predecessor) rather than hand-resolving text that will just conflict again on the next commit.
     - When a HEAD-side conflict block looks like dead/stale code inconsistent with the rest of the file (e.g. an old calling convention no longer used elsewhere in the same file), verify against the source branch's own final version of that file before trusting either side blindly.
3. Verify before pushing: run the most relevant existing tests, a typecheck, or at minimum a syntax check on every file touched by conflict resolution. Never push a conflict resolution that wasn't exercised somehow.
4. Push the branch and open one PR per commit against target:
   - Title: `<original PR title> (backport of #<N>)`.
   - Body: what it backports (link the source PR), any dependency PRs this one is stacked on plus the required merge order, and — if conflicts needed resolving — a plain description of the reasoning and how it was verified (tests run, typecheck clean, etc.).

## Step 6: Report

Give the user a table: PR opened per commit, the merge order required for any stacked chain (call out explicitly which PRs must land before which), and which candidate commits were skipped because they were already present on target (with which existing target commit/PR made them redundant, if known).

## Edge cases

- **No candidate commits found**: say so plainly and stop. Do not fabricate a backport for an empty diff.
- **Commit has no associated PR** (direct push): fall back to referencing the commit SHA and message in the PR body instead of a PR link.
- **Updating an existing backport PR whose target has advanced**: if a predecessor in a stacked chain merges and a later PR in the chain now conflicts against the new target tip, merge target into that branch and resolve using the same judgment as Step 5 — don't recreate the branch from scratch unless asked.
- Never force-push over an already-open backport branch without first checking its current state (`gh pr view`) — another commit or review feedback may already be on it.
- Never touch a PR the user has explicitly said to leave alone.
