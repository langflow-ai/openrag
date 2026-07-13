# OpenRAG Dev Plugin

Internal developer/QA workflow skills for OpenRAG contributors. Unlike the `openrag` plugin (guided install, SDK integration — aimed at people using OpenRAG), this plugin is for people working *on* OpenRAG: it assumes access to the project's git history and, for full functionality, the GitHub CLI.

## Skills

| Skill | Purpose |
| --- | --- |
| `openrag_dev_qa_handoff` | Generate a QA handoff message for a release branch: per-commit fix summary, PR link, and test steps within a date range. See [`skills/qa-handoff/SKILL.md`](skills/qa-handoff/SKILL.md). |

## Install

### Option 1: Clone this repo and use Claude Code (recommended for contributors)

No install step. `.claude/skills/qa-handoff` already symlinks into `plugins/openrag-dev/skills/qa-handoff`, so Claude Code auto-discovers it when you start a session in this repo. Invoke it with `/qa-handoff`, or just ask for a QA handoff — Claude triggers it automatically based on the skill's `description`.

### Option 2: Install globally via the Claude Code marketplace

```
/plugin marketplace add langflow-ai/openrag
/plugin install openrag-dev@openrag
```

Makes the skill available in any repo, not just this checkout — useful since a QA handoff only needs `git`/`gh` access to whichever repo's branch you're asking about.

### Option 3: Claude Agent SDK / other skill-aware runtimes

Point your skill loader at `plugins/openrag-dev/skills/`. Each subdirectory is one skill (currently just `qa-handoff`).

### Option 4: Any other agent (generic)

Read `plugins/openrag-dev/skills/qa-handoff/SKILL.md` directly — the frontmatter `description` says when to use it, the body is the instruction set.

### Option 5: `npx skills` CLI (any repo, any supported agent)

[`npx skills`](https://github.com/vercel-labs/skills) is a third-party, agent-agnostic package manager for `SKILL.md`-based skills (Claude Code, Cursor, OpenCode, Codex, and others). It scans a source for `SKILL.md` files and installs them into the target agent's skills directory.

```bash
# from a clone of this repo
npx skills add . --skill qa-handoff

# once this repo/branch is pushed, from anywhere
npx skills add langflow-ai/openrag --skill qa-handoff

# or point at the skill directly
npx skills add https://github.com/langflow-ai/openrag/tree/main/plugins/openrag-dev/skills/qa-handoff
```

This only sees what's actually pushed to the remote (or a local path you point it at directly) — it doesn't read uncommitted or unpushed local changes unless you use the local-path form above.

## Use

Ask your agent for a QA handoff, for example:

- "Generate a QA handoff for release-1.52"
- "QA handoff for main, last 3 days"
- "Prepare a release handoff for release-saas-ga-0.6.2 from July 10th"

If you don't give a date range, the skill asks how many days back to look and defaults to the **last 24 hours** if you don't answer.

Output always follows the standard layout in [`skills/qa-handoff/TEMPLATE.md`](skills/qa-handoff/TEMPLATE.md): a header (branch, date range, latest SHA, commit count) followed by one section per commit — a plain-English one-liner, what was fixed, the PR link, and "what to test" / "how to test" bullet lists grounded in the commit's diff and PR description.

## Requirements

- `git`, with the branch in question fetchable
- `gh` CLI, authenticated (`gh auth status`) — optional but recommended; without it, PR links fall back to numbers parsed from commit messages and PR-body testing notes aren't available

## Adding more skills to this plugin

Follow the same authoring steps as the rest of the repo's skills — see [`plugins/README.md`](../README.md#authoring-new-skills). Bump this plugin's `version` in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) when the skill set changes materially.
