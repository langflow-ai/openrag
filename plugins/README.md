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
│   └── openrag/                   # one plugin, can grow to many
│       ├── .claude-plugin/
│       │   └── plugin.json        # plugin manifest (name, version, repo)
│       └── skills/
│           ├── install/SKILL.md   # guided OpenRAG installation
│           └── sdk/SKILL.md       # OpenRAG SDK integration helper
├── .claude/
│   └── skills/                    # symlinks into plugins/openrag/skills
│       ├── install -> ../../plugins/openrag/skills/install
│       └── sdk     -> ../../plugins/openrag/skills/sdk
└── AGENTS.md                      # entry point for any agent working in the repo
```

The skills under `plugins/openrag/skills/` are the single source of truth. Everything else (`.claude/skills/` symlinks, marketplace/plugin manifests, `AGENTS.md`) points at them, so edits in one place propagate everywhere.

## How users consume the skills

There are four ways to get these skills in front of an agent.

### 1. Clone this repo and use Claude Code

No install step. `.claude/skills/` symlinks into the plugin, so Claude Code auto-discovers `install` and `sdk` when it starts in this directory. Invoke with `/install` or `/sdk`, or let Claude trigger them automatically based on the `description` fields.

### 2. Install into Claude Code globally (any project)

```
/plugin marketplace add langflow-ai/openrag
/plugin install openrag@openrag
```

The first command registers this repo as a marketplace (reads `.claude-plugin/marketplace.json`). The second installs the `openrag` plugin defined in `plugins/openrag/.claude-plugin/plugin.json`. The skills then work in any directory, not just this repo.

### 3. Load from the Claude Agent SDK or other skill-aware runtimes

Point your skill loader at `plugins/openrag/skills/`. Each subdirectory is one skill. The SKILL.md format is Anthropic's Agent Skills spec and is consumed by the Claude Agent SDK and compatible runtimes.

### 4. Any other agent (generic)

Read `SKILL.md` directly. The frontmatter `description` tells the agent when the skill is relevant; the markdown body is the instruction set. `AGENTS.md` at the repo root lists the available skills and links to them.

## Authoring new skills

When adding a skill:

1. Create `plugins/openrag/skills/<name>/SKILL.md` with frontmatter:
   ```yaml
   ---
   name: <name>
   description: When the agent should invoke this skill (one sentence, specific).
   ---
   ```
2. Add a symlink so Claude Code in this repo picks it up:
   ```
   ln -s ../../plugins/openrag/skills/<name> .claude/skills/<name>
   ```
3. List it in `AGENTS.md` so non-Claude agents can find it.
4. Keep the body **agent-neutral**: no references to tools or features that only exist in one runtime (no `TodoWrite`, no specific slash-command assumptions, no hook-based automations). Describe actions in generic terms: read files, run commands, fetch URLs, ask the user.
5. Put Claude-Code-specific configuration (permissions, hooks) in `plugin.json` or `.claude/`, not in `SKILL.md`.

## Versioning

Bump `plugins/openrag/.claude-plugin/plugin.json`'s `version` field when the skill set changes materially. Marketplace users pin to specific versions.
