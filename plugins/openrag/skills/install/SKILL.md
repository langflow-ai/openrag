---
name: openrag_install
description: Plan and execute a minimal OpenRAG installation with requirement drafting, task tracking, configuration guidance, and local verification
---

When the user asks to install OpenRAG, follow this workflow in order.

## Initial assessment phase
Before starting installation, check for an existing OpenRAG installation:
1. Check if `~/.openrag/tui/.env` exists
2. If it exists:
   - Read the configuration to understand what's already set up
   - Check if services are currently running with `docker compose ps` for the generated OpenRAG compose file, or by filtering on the compose project/labels instead of `docker ps --filter "name=openrag"`
   - Inform the user about the existing installation
   - Ask if they want to:
     - Start existing services (if stopped)
     - Reconfigure existing installation
     - Verify existing installation
     - Proceed with fresh installation (will use existing config)
3. If no existing installation found, proceed with fresh installation workflow

## Primary goals
- Produce a grounded installation spec in `requirements.md`
- Break the work into executable tasks in `todo.md`
- Implement all tasks that can be completed in the current environment
- Pause for user action when a task requires credentials, configuration choices, or other interactive input
- Verify the installation locally until `http://localhost:3000` launches without startup errors and `http://localhost:5001/docs` is reachable
- Treat browser onboarding after the app launches as user-owned and outside installation completion

## Requirements authoring phase
First, create or update `requirements.md` using the official OpenRAG installation documentation:
- Use `https://docs.openr.ag/install-options` as the source of truth
- Do not hallucinate implementation details that are not supported by the documentation or the local environment
- Prioritize the minimal installation path and the fewest necessary steps
- Organize requirements into logical categories
- Use numbered identifiers in the format `REQ-001`, `REQ-002`, and so on
- Include acceptance criteria for every requirement
- Include requirements covering:
  - System prerequisites and resource requirements
  - Configuration and security
  - Platform compatibility
  - Edge cases and troubleshooting considerations

Include the following specific requirement in the spec:
- Non-containerized service: `docling-serve` on port `5001`
- It is a required bundled Python service
- It is bundled with OpenRAG and managed by `uvx` or `uv`
- It should be automatically started and stopped via `uvx openrag`
- It should be available at `http://localhost:5001/docs`
- Verification should include either `lsof -i :5001` or `curl http://localhost:5001/docs`
- Do not immediately flag failure if `http://localhost:5001/docs` is not ready right after startup; wait and re-check because `docling-serve` may come up after the main OpenRAG services

## Requirements review phase
After drafting `requirements.md`:
- Review it for gaps, ambiguities, contradictions, and missing edge cases
- Tighten vague language
- Add missing acceptance criteria where needed
- Update the file before moving to implementation planning

## Task planning and execution phase
After `requirements.md` is stable:
1. Read `requirements.md`
2. Create `todo.md` that breaks the work into concrete tasks
3. Implement each task that is relevant to the current environment
4. For user-interactive tasks, do not guess or fabricate values; instruct the user to complete the step and confirm when done
5. Mark tasks complete in `todo.md` only after they pass validation
6. If troubleshooting partially started OpenRAG services, stop all services before attempting to start them again

## CRITICAL: Interactive Terminal Limitation
**Most agent shell tools cannot drive interactive terminal applications that require user input.** This includes any command that renders a TUI, prompts for passwords, or expects arrow-key navigation.

When the installation reaches the point where `uvx openrag` needs to be run:

### What NOT to do:
- Do NOT attempt to run `uvx openrag` through the agent's shell tool expecting to interact with it
- Do NOT try to use background processes for interactive commands
- Do NOT assume you can send input to an already-running interactive terminal

### What TO do:
1. **Explicitly instruct the user** to open a NEW terminal window/tab outside the agent's shell
2. Provide the exact command to run: `uvx --python 3.13 openrag`
3. Give step-by-step instructions for what they will see and how to respond:
   - First run: Select "Reconfigure" (option 2)
   - Set OpenSearch Admin password (MUST be strong)
   - Set Langflow Admin password (can autogenerate or manual)
   - Accept defaults for other prompts (press 'N' or skip)
   - Return to menu and select "Start services" (option 1)
   - Wait for "Services are running" message
4. **Wait for user confirmation** that they completed the steps
5. **After confirmation**, verify the installation using non-interactive commands:
   - Check container status: `docker ps --filter "name=openrag"`
   - Verify ports: `lsof -i :3000` and `lsof -i :5001`
   - Test endpoints: `curl http://localhost:3000` and `curl http://localhost:5001/docs`

### Example user instruction format:
```
The next step requires running an interactive command that I cannot control directly.

Please open a NEW terminal window (separate from this agent session) and run:

    uvx --python 3.13 openrag

You will see a menu. Follow these steps:
1. Type '2' and press Enter (Reconfigure)
2. Enter a STRONG OpenSearch Admin password (write it down!)
3. Enter Langflow Admin password (or autogenerate)
4. Press 'N' or skip for other prompts
5. Type '1' and press Enter (Start services)
6. Wait for "Services are running" message

Once complete, come back here and confirm: "Configuration and services started successfully"
```

## User-interactive guidance
When a task requires user input, secret values, or interactive terminal control:
- Tell the user exactly what action they need to take
- Explain how you will verify completion
- Wait for confirmation before proceeding
- Explicitly instruct the user that the OpenSearch password must be strong, defaults can be used for all other values to get started quickly
- **ALWAYS instruct users to run `uvx openrag` in a separate terminal outside the agent's shell**
- Provide explicit step-by-step guidance for what they will see and how to respond
- After user confirms completion, verify using non-interactive commands

## Safety and accuracy rules
- Prefer official documentation and observed local state over assumptions
- Do not invent ports, services, commands, configuration keys, or file locations unless verified
- Keep installation steps as simple and minimal as possible
- Use secure defaults and align with OWASP-style handling of secrets and credentials
- Call out platform-specific limitations when they affect installation or verification
- **Be explicit that the agent's shell cannot drive interactive TUI applications**
- **Never attempt to run `uvx openrag` interactively through the agent's shell**
- Do not treat delayed startup alone as a failure condition when output is still progressing normally

## Verification and completion
Before considering the installation complete:
- Verify all completed tasks against the acceptance criteria in `requirements.md`
- Confirm required services are running
- Verify `http://localhost:3000` first
- Wait briefly, then verify `docling-serve` is reachable at `http://localhost:5001/docs`
- If OpenRAG services were restarted during troubleshooting, verify they are all healthy after the clean restart
- Only escalate to troubleshooting if repeated checks fail after a reasonable delay or the terminal shows explicit errors
- Consider the installation complete once the app launches without startup errors on `http://localhost:3000` and `http://localhost:5001/docs` is reachable
- Do not treat provider selection or browser onboarding completion as part of installation completion

## Collaboration style
- Be explicit about what is known, what is inferred, and what still needs verification
- Surface ambiguities early and resolve them before implementation
- Keep outputs structured and easy to audit
- Iterate on `requirements.md` and `todo.md` as new validated information is discovered
- **Clearly communicate when user action is required in a separate terminal**
