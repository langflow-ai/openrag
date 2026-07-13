# OpenRAG Agent Plugins

This directory contains agent **skills** that help users work with OpenRAG. A skill is a `SKILL.md` file (YAML frontmatter + markdown body) that an AI agent reads to know *when* and *how* to assist with a particular task.

The canonical content lives here; it is surfaced to agents through several distribution paths described below.

## Layout

```
openrag/
├── .claude-plugin/
│   └── marketplace.json           # turns the repo into a Claude Code marketplace
├── plugins/
│   ├── README.md                  # this file
│   ├── openrag/                   # end-user facing: install + SDK integration
│   │   ├── .claude-plugin/
│   │   │   └── plugin.json        # plugin manifest (name, version, repo)
│   │   └── skills/
│   │       ├── install/SKILL.md   # guided OpenRAG installation
│   │       └── sdk/SKILL.md       # OpenRAG SDK integration helper
│   └── openrag-dev/                # internal contributor/QA workflow skills
│       ├── .claude-plugin/
│       │   └── plugin.json
│       └── skills/
│           └── qa-handoff/SKILL.md # release-branch QA handoff generator
├── .claude/
│   └── skills/                    # symlinks into plugins/<plugin>/skills
│       ├── install    -> ../../plugins/openrag/skills/install
│       ├── sdk         -> ../../plugins/openrag/skills/sdk
│       └── qa-handoff -> ../../plugins/openrag-dev/skills/qa-handoff
└── AGENTS.md                      # entry point for any agent working in the repo
```

The skills under each `plugins/<plugin>/skills/` directory are the single source of truth. Everything else (`.claude/skills/` symlinks, marketplace/plugin manifests, `AGENTS.md`) points at them, so edits in one place propagate everywhere.

## Available plugins

| Plugin | Audience | README |
| --- | --- | --- |
| `openrag` | People using/installing OpenRAG | [`plugins/openrag/`](openrag/) — install and SDK-integration skills (no dedicated README yet; see this file) |
| `openrag-dev` | OpenRAG contributors | [`plugins/openrag-dev/README.md`](openrag-dev/README.md) — internal dev/QA workflow skills |

## How users consume the skills

There are five ways to get these skills in front of an agent. The examples below use the `openrag` plugin; swap in `openrag-dev` (or any future plugin) to get that one instead — see its README for plugin-specific details.

### 1. Clone this repo and use Claude Code

No install step. `.claude/skills/` symlinks into each plugin, so Claude Code auto-discovers every skill (`install`, `sdk`, `qa-handoff`, ...) when it starts in this directory. Invoke with `/install`, `/sdk`, `/qa-handoff`, etc., or let Claude trigger them automatically based on the `description` fields.

### 2. Install into Claude Code globally (any project)

```
/plugin marketplace add langflow-ai/openrag
/plugin install openrag@openrag
/plugin install openrag-dev@openrag
```

The first command registers this repo as a marketplace (reads `.claude-plugin/marketplace.json`). The next two install individual plugins, each defined by its own `plugins/<plugin>/.claude-plugin/plugin.json`. Installed skills then work in any directory, not just this repo.

### 3. Load from the Claude Agent SDK or other skill-aware runtimes

Point your skill loader at `plugins/<plugin>/skills/`. Each subdirectory is one skill. The SKILL.md format is Anthropic's Agent Skills spec and is consumed by the Claude Agent SDK and compatible runtimes.

### 4. Any other agent (generic)

Read `SKILL.md` directly. The frontmatter `description` tells the agent when the skill is relevant; the markdown body is the instruction set. `AGENTS.md` at the repo root lists the available skills and links to them.

### 5. `npx skills` CLI (any repo, any supported agent)

[`npx skills`](https://github.com/vercel-labs/skills) is a third-party, agent-agnostic package manager for `SKILL.md`-based skills — it works with Claude Code, Cursor, OpenCode, Codex, and others. It scans a source for `SKILL.md` files and installs them into the target agent's skills directory (symlinked by default).

```bash
# from a clone of this repo — discovers every SKILL.md across all plugins
npx skills add . --list

# once pushed, from anywhere
npx skills add langflow-ai/openrag --skill qa-handoff

# or point at one skill directly
npx skills add https://github.com/langflow-ai/openrag/tree/main/plugins/openrag-dev/skills/qa-handoff
```

This is not part of the Claude Code plugin/marketplace system above — it's a separate, agent-agnostic CLI. It only sees what's pushed to the remote (or a local path given directly), not uncommitted local changes.

## Authoring new skills

When adding a skill:

1. Create `plugins/<plugin>/skills/<name>/SKILL.md` (e.g. `plugins/openrag/skills/<name>/SKILL.md` for end-user facing skills, `plugins/openrag-dev/skills/<name>/SKILL.md` for contributor/QA workflow skills) with frontmatter:
   ```yaml
   ---
   name: <name>
   description: When the agent should invoke this skill (one sentence, specific).
   ---
   ```
2. Add a symlink so Claude Code in this repo picks it up:
   ```
   ln -s ../../plugins/<plugin>/skills/<name> .claude/skills/<name>
   ```
3. List it in `AGENTS.md` so non-Claude agents can find it.
4. Keep the body **agent-neutral**: no references to tools or features that only exist in one runtime (no `TodoWrite`, no specific slash-command assumptions, no hook-based automations). Describe actions in generic terms: read files, run commands, fetch URLs, ask the user.
5. Put Claude-Code-specific configuration (permissions, hooks) in `plugin.json` or `.claude/`, not in `SKILL.md`.

## Versioning

Bump the relevant plugin's `.claude-plugin/plugin.json` `version` field (e.g. `plugins/openrag/.claude-plugin/plugin.json`, `plugins/openrag-dev/.claude-plugin/plugin.json`) when that plugin's skill set changes materially. Marketplace users pin to specific versions.
