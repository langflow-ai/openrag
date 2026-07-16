# OpenRAG Dev Plugin

Internal developer/QA workflow skills for OpenRAG contributors. Unlike the `openrag` plugin (guided install, SDK integration — aimed at people using OpenRAG), this plugin is for people working *on* OpenRAG: it assumes access to the project's git history and, for full functionality, the GitHub CLI.

## Skills

| Skill | Purpose |
| --- | --- |
| `openrag_dev_qa_handoff` | Generate a QA handoff message for a release branch: per-commit fix summary, PR link, and test steps within a date range. See [`skills/qa-handoff/SKILL.md`](skills/qa-handoff/SKILL.md). |
| `openrag_dev_backport` | Backport commits/PRs from a source branch into a target branch (e.g. a release branch into main): one PR per commit, correctly ordered, conflicts resolved and verified. See [`skills/backport/SKILL.md`](skills/backport/SKILL.md). |

## Install

### Option 1: Clone this repo and use Claude Code (recommended for contributors)

No install step. `.claude/skills/qa-handoff` and `.claude/skills/backport` already symlink into their respective `plugins/openrag-dev/skills/` directories, so Claude Code auto-discovers both when you start a session in this repo. Invoke with `/qa-handoff` or `/backport`, or just ask — Claude triggers the right one automatically based on each skill's `description`.

### Option 2: Install globally via the Claude Code marketplace

```
/plugin marketplace add langflow-ai/openrag
/plugin install openrag-dev@openrag
```

Makes the skill available in any repo, not just this checkout — useful since a QA handoff only needs `git`/`gh` access to whichever repo's branch you're asking about.

### Option 3: Claude Agent SDK / other skill-aware runtimes

Point your skill loader at `plugins/openrag-dev/skills/`. Each subdirectory is one skill (`qa-handoff`, `backport`).

### Option 4: Any other agent (generic)

Read the relevant `SKILL.md` directly (`plugins/openrag-dev/skills/qa-handoff/SKILL.md` or `plugins/openrag-dev/skills/backport/SKILL.md`) — the frontmatter `description` says when to use it, the body is the instruction set.

### Option 5: `npx skills` CLI (any repo, any supported agent)

[`npx skills`](https://github.com/vercel-labs/skills) is a third-party, agent-agnostic package manager for `SKILL.md`-based skills (Claude Code, Cursor, OpenCode, Codex, and others). It scans a source for `SKILL.md` files and installs them into the target agent's skills directory.

```bash
# from a clone of this repo — --skill matches the SKILL.md frontmatter `name`, not the directory name
npx skills add . --skill openrag_dev_qa_handoff
npx skills add . --skill openrag_dev_backport

# once this repo/branch is pushed, from anywhere
npx skills add langflow-ai/openrag --skill openrag_dev_qa_handoff

# or point at the skill's directory directly (no --skill needed)
npx skills add https://github.com/langflow-ai/openrag/tree/main/plugins/openrag-dev/skills/qa-handoff
```

This only sees what's actually pushed to the remote (or a local path you point it at directly) — it doesn't read uncommitted or unpushed local changes unless you use the local-path form above.

## Use

### QA handoff

Ask your agent for a QA handoff, for example:

- "Generate a QA handoff for release-1.52"
- "QA handoff for main, last 3 days"
- "Prepare a release handoff for release-saas-ga-0.6.2 from July 10th"

If you don't give a date range, the skill asks how many days back to look and defaults to the **last 24 hours** if you don't answer.

Output always follows the standard layout in [`skills/qa-handoff/TEMPLATE.md`](skills/qa-handoff/TEMPLATE.md): a header (branch, date range, latest SHA, commit count) followed by one section per commit — a plain-English one-liner, what was fixed, the PR link, and "what to test" / "how to test" bullet lists grounded in the commit's diff and PR description.

### Backport

Ask your agent to backport a branch, for example:

- "Backport release-saas-ga-0.6.2 into main"
- "Which PRs are in release-1.52 but not main? Backport them."
- "Forward-port everything in this release branch that hasn't landed on main yet"

The skill lists commits present on the source branch but missing from the target, skips anything already applied under a different SHA, works out cross-commit ordering from file overlap, then opens one PR per commit against the target branch — conflicts are inspected and resolved (never guessed), and every resolution is verified with the relevant tests/typecheck before pushing. See [`skills/backport/SKILL.md`](skills/backport/SKILL.md) for the full procedure and [`skills/backport/TEMPLATE.md`](skills/backport/TEMPLATE.md) for the PR body layout it uses.

## Requirements

- `git`, with both branches fetchable
- `gh` CLI, authenticated (`gh auth status`) — required for `backport` (creating PRs); optional but recommended for `qa-handoff` (without it, PR links fall back to numbers parsed from commit messages and PR-body testing notes aren't available)

## Adding more skills to this plugin

Follow the same authoring steps as the rest of the repo's skills — see [`plugins/README.md`](../README.md#authoring-new-skills). Bump this plugin's `version` in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) when the skill set changes materially.
