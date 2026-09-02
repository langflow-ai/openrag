# BomaRAG Agent Plugins

This directory contains agent **skills** that help users work with BomaRAG. A skill is a `SKILL.md` file (YAML frontmatter + markdown body) that an AI agent reads to know *when* and *how* to assist with a particular task.

The canonical content lives here; it is surfaced to agents through several distribution paths described below.

## Layout

```
bomarag/
├── .claude-plugin/
│   └── marketplace.json           # turns the repo into a Claude Code marketplace
├── plugins/
│   ├── README.md                  # this file
│   └── bomarag/                   # one plugin, can grow to many
│       ├── .claude-plugin/
│       │   └── plugin.json        # plugin manifest (name, version, repo)
│       └── skills/
│           ├── install/SKILL.md   # guided BomaRAG installation
│           ├── sdk/SKILL.md       # BomaRAG SDK integration helper
│           └── dev-stack/SKILL.md # local dev stack runner (infra + backend + frontend)
├── .claude/
│   └── skills/                    # symlinks into plugins/bomarag/skills
│       ├── install   -> ../../plugins/bomarag/skills/install
│       ├── sdk       -> ../../plugins/bomarag/skills/sdk
│       └── dev-stack -> ../../plugins/bomarag/skills/dev-stack
└── AGENTS.md                      # entry point for any agent working in the repo
```

The skills under `plugins/bomarag/skills/` are the single source of truth. Everything else (`.claude/skills/` symlinks, marketplace/plugin manifests, `AGENTS.md`) points at them, so edits in one place propagate everywhere.

## How users consume the skills

There are four ways to get these skills in front of an agent.

### 1. Clone this repo and use Claude Code

No install step. `.claude/skills/` symlinks into the plugin, so Claude Code auto-discovers `install`, `sdk`, and `dev-stack` when it starts in this directory. Invoke with `/install`, `/sdk`, or `/dev-stack`, or let Claude trigger them automatically based on the `description` fields.

### 2. Install into Claude Code globally (any project)

```
/plugin marketplace add ABISHAIMWANJA/bomarag
/plugin install bomarag@bomarag
```

The first command registers this repo as a marketplace (reads `.claude-plugin/marketplace.json`). The second installs the `bomarag` plugin defined in `plugins/bomarag/.claude-plugin/plugin.json`. The skills then work in any directory, not just this repo.

### 3. Load from the Claude Agent SDK or other skill-aware runtimes

Point your skill loader at `plugins/bomarag/skills/`. Each subdirectory is one skill. The SKILL.md format is Anthropic's Agent Skills spec and is consumed by the Claude Agent SDK and compatible runtimes.

### 4. Any other agent (generic)

Read `SKILL.md` directly. The frontmatter `description` tells the agent when the skill is relevant; the markdown body is the instruction set. `AGENTS.md` at the repo root lists the available skills and links to them.

## Authoring new skills

When adding a skill:

1. Create `plugins/bomarag/skills/<name>/SKILL.md` with frontmatter:
   ```yaml
   ---
   name: <name>
   description: When the agent should invoke this skill (one sentence, specific).
   ---
   ```
2. Add a symlink so Claude Code in this repo picks it up:
   ```
   ln -s ../../plugins/bomarag/skills/<name> .claude/skills/<name>
   ```
3. List it in `AGENTS.md` so non-Claude agents can find it.
4. Keep the body **agent-neutral**: no references to tools or features that only exist in one runtime (no `TodoWrite`, no specific slash-command assumptions, no hook-based automations). Describe actions in generic terms: read files, run commands, fetch URLs, ask the user.
5. Put Claude-Code-specific configuration (permissions, hooks) in `plugin.json` or `.claude/`, not in `SKILL.md`.

## Versioning

Bump `plugins/bomarag/.claude-plugin/plugin.json`'s `version` field when the skill set changes materially. Marketplace users pin to specific versions.
