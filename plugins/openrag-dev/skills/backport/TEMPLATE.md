# Backport PR body — <source branch> → <target branch>

## Summary
Backports #<source PR number> from `<source branch>` to `<target branch>`.

<1-2 sentence plain-English description of what the change does>

## Depends on
<!-- omit this section entirely if the PR has no dependencies -->
Depends on <#PR> (<short description>) — stacked because it touches <file(s)/region> in the same area. Merge order: <#PR1> → <#PR2> → ... → this PR.

## Conflict notes
<!-- omit this section entirely if the cherry-pick was clean -->
Cherry-pick conflicted in `<file>` against <unrelated feature / ordering issue already on target>. Resolved by <what was kept/changed and why>. Verified with <tests run / typecheck / syntax check — name the actual command and result>.

## Test plan
- [ ] <verification already run, e.g. "`pytest tests/unit/...` — N passed">
- [ ] CI passes
