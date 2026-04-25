# Agent Instructions

This repository ships with **agent skills** that any compliant agent can use to help users install OpenRAG and integrate the OpenRAG SDK. The canonical skill files are markdown with YAML frontmatter (the [Agent Skills](https://github.com/anthropics/skills) format), and live under `plugins/openrag/skills/`.

## Available skills

| Skill | File | Purpose |
| --- | --- | --- |
| `openrag_install` | [`plugins/openrag/skills/install/SKILL.md`](plugins/openrag/skills/install/SKILL.md) | Plan and execute a minimal OpenRAG installation, verify locally. |
| `openrag_sdk` | [`plugins/openrag/skills/sdk/SKILL.md`](plugins/openrag/skills/sdk/SKILL.md) | Guide SDK integration (Python, TypeScript, MCP) with code examples. |

## How to use these skills

Pick the path that matches your agent runtime.

### Claude Code (this repo)

`.claude/skills/` symlinks into the plugin, so after cloning the repo the skills are auto-discovered by Claude Code — invoke with `/install` or `/sdk`, or let Claude trigger them automatically based on the description fields.

### Claude Code (install globally, any repo)

```
/plugin marketplace add langflow-ai/openrag
/plugin install openrag@openrag
```

### Claude Agent SDK / other skill-aware runtimes

Point your skill loader at `plugins/openrag/skills/`. Each subdirectory is one skill.

### Any other agent (generic)

Read the `SKILL.md` files directly. The frontmatter `description` tells you when the skill is relevant; the body is the instruction set to follow.

## Skill authoring notes

- Skill bodies are intentionally kept agent-neutral. Do not add references to tools or features that only exist in one runtime (for example, do not name specific slash commands, hook systems, or task-tracking tools).
- Claude-Code-specific plumbing belongs in `plugin.json` or `.claude/`, not in `SKILL.md`.
- See `plugins/README.md` for the full layout and distribution model.
