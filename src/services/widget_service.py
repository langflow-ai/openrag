"""Widget generation service using Claude Agent SDK."""
import os
import json
import subprocess
import asyncio
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from utils.logging_config import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from services.widget_mcp_server import WidgetMCPServer

# Claude Agent SDK imports
try:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
except ImportError:
    raise ImportError(
        "Claude Agent SDK not installed. Please install with: pip install claude-agent-sdk"
    )


class WidgetService:
    """Service for generating React widget components using Claude Agent SDK."""

    def __init__(self, mcp_server: "WidgetMCPServer | None" = None):
        self.widgets_dir = os.path.abspath("widgets")
        self.assets_dir = os.path.join(self.widgets_dir, "assets")
        os.makedirs(self.widgets_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)
        logger.info("Widget service initialized", widgets_dir=self.widgets_dir)
        self._dependency_install_lock = threading.Lock()
        self._install_task_started = False
        self._mcp_server = mcp_server

        # Check if npm and vite are available
        self._check_build_dependencies()
        self._refresh_mcp_registry()

    async def _sync_widgets_to_flow_prompt(self) -> None:
        """Update the Langflow chat flow system prompt with current widget instructions."""
        try:
            from config.settings import get_openrag_config
            from services.widget_instruction_service import get_widget_instruction_block
            from services.flows_service import FlowsService
            import re

            config = get_openrag_config()

            # Only update if config has been edited (onboarding completed)
            if not config.edited:
                logger.debug("Skipping widget prompt sync - config not yet edited")
                return

            # Get the base system prompt (without widgets)
            base_prompt = config.agent.system_prompt or ""

            # Strip out any existing widget instruction block from base prompt
            # Pattern: "You are able to display the following list of UI widgets:" ... "```\n{uri}\n```"
            widget_block_pattern = r"You are able to display the following list of UI widgets:.*?```\n[^\n]+\n```"
            base_prompt_cleaned = re.sub(widget_block_pattern, "", base_prompt, flags=re.DOTALL).strip()

            # Get fresh widget instructions
            widget_block = await get_widget_instruction_block(force_refresh=True)

            # Combine widget block FIRST, then cleaned base prompt
            if widget_block:
                combined_prompt = (
                    f"{widget_block}\n\n{base_prompt_cleaned}"
                    if base_prompt_cleaned
                    else widget_block
                )
            else:
                combined_prompt = base_prompt_cleaned

            # Update the flow
            flows_service = FlowsService()
            provider = config.provider.model_provider.lower()
            await flows_service.update_chat_flow_system_prompt(combined_prompt, provider)

            logger.info("Successfully synced widget instructions to flow system prompt")
        except Exception as e:
            logger.error("Failed to sync widgets to flow prompt", error=str(e))

    async def generate_widget(
        self, widget_id: str, prompt: str, user_id: str, base_widget_id: str = None
    ) -> Dict[str, Any]:
        """
        Generate a React widget component using the Claude Agent SDK.
        If base_widget_id is provided, load the existing widget and iterate on it.
        """
        try:
            logger.info(
                "Generating widget",
                widget_id=widget_id,
                prompt=prompt[:100],
                user_id=user_id,
                base_widget_id=base_widget_id,
            )

            # Ensure API key exists
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise Exception("ANTHROPIC_API_KEY not set in environment")

            # If base_widget_id is provided, load existing widget code
            base_jsx = None
            base_css = None
            base_metadata: Dict[str, Any] | None = None
            if base_widget_id:
                base_widget = await self.get_widget(base_widget_id)
                if base_widget:
                    base_jsx = base_widget.get("jsx_content")
                    base_css = base_widget.get("css_content")
                    base_metadata = base_widget.get("metadata") or {}
                    logger.info("Loaded base widget for iteration", base_widget_id=base_widget_id)

            # System-level instructions for the Claude agent
            system_prompt = """You are an expert React developer.
Generate a complete, self-contained React widget component based on the user's request.

Requirements:
1. Return TWO separate code blocks: one for JSX and one for CSS
2. Use modern React with hooks (functional components)
3. The component must be named 'Widget' and be the default export
4. Make it visually appealing with good UX
5. Keep it self-contained - no external dependencies beyond React
6. Include proper error handling
7. IMPORTANT: Add rendering code at the bottom that creates a root and renders the component
8. Use the specified color palette and design system below
9. IMPORTANT: The widget will be displayed in a 768x404px container. Design for a maximum height of 404px and ensure content fits or scrolls appropriately within this constraint

Design System:
- Font: Use platform-native system fonts: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif
- DO NOT apply colors to backgrounds in text input areas or textareas

Color Palette (Light Mode - default):
- Background Primary: #FFFFFF
- Background Secondary: #E6E6E6
- Background Tertiary: #F3F3F3
- Text Primary: #000000
- Text Secondary: #505050
- Text Tertiary: #BFBFBF
- Text Inverted: #FFFFFF
- Accent Blue: #265FFF
- Accent Red: #E6252A
- Accent Orange: #E2561F
- Accent Green: #0B8635

Color Palette (Dark Mode - use @media (prefers-color-scheme: dark)):
- Background Primary: #121212
- Background Secondary: #303030
- Background Tertiary: #414141
- Text Primary: #FFFFFF
- Text Secondary: #C0C0C0
- Text Tertiary: #AFAFAF
- Text Inverted: #FFFFFF
- Accent Blue: #265FFF
- Accent Red: #FF5858
- Accent Orange: #FF926C
- Accent Green: #1AD977

Output format:
```jsx
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';

function Widget() {
  // Component implementation
  return (
    <div className="widget-container">
      {/* Your JSX here */}
    </div>
  );
}

// Render the widget
const root = createRoot(document.getElementById('root'));
root.render(<Widget />);
```

```css
/* Your CSS styles here - include both light and dark mode */
.widget-container {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
  background: #FFFFFF;
  color: #000000;
  /* styles */
}

@media (prefers-color-scheme: dark) {
  .widget-container {
    background: #121212;
    color: #FFFFFF;
    /* dark mode styles */
  }
}
```"""

            # Configure the Claude Agent
            options = ClaudeAgentOptions(
                system_prompt=system_prompt,
                model="claude-sonnet-4-5-20250929",
            )

            # Create the Claude agent client
            client = ClaudeSDKClient(options=options)
            await client.connect()

            try:
                logger.debug("Starting Claude agent query...")

                # Build the query - if iterating, include the base widget code
                if base_jsx:
                    iteration_prompt = f"""I have an existing React widget. Please modify it based on my request.

Current JSX:
```jsx
{base_jsx}
```

Current CSS:
```css
{base_css or '/* No CSS */'}
```

Request: {prompt}

Please return the COMPLETE updated widget code (not just the changes) in the same format with JSX and CSS code blocks."""
                    query = iteration_prompt
                else:
                    query = prompt

                # Send the query (returns None, doesn't return content)
                await client.query(query)

                # Collect response text from messages
                response_text = ""
                async for message in client.receive_response():
                    # Check if it's an AssistantMessage with TextBlock content
                    if hasattr(message, 'content'):
                        for block in message.content:
                            if hasattr(block, 'text'):
                                response_text += block.text

                if not response_text:
                    raise Exception("No response text from Claude Agent SDK")

                logger.debug("Extracted response text", length=len(response_text))
            finally:
                await client.disconnect()

            # Extract code blocks
            jsx_code = self._extract_code_block(response_text, "jsx", "javascript", "js")
            css_code = self._extract_code_block(response_text, "css")
            has_css = css_code is not None
            jsx_code = self._normalize_widget_css_import(jsx_code, widget_id, has_css)

            if not jsx_code:
                raise Exception("No JSX code block found in response")

            # Write files to widgets/assets/{widget_id}/ directory
            widget_assets_dir = os.path.join(self.widgets_dir, "assets", widget_id)
            os.makedirs(widget_assets_dir, exist_ok=True)

            jsx_path = os.path.join(widget_assets_dir, f"{widget_id}.jsx")
            with open(jsx_path, "w") as f:
                f.write(jsx_code)

            css_path = None
            if css_code:
                css_path = os.path.join(widget_assets_dir, f"{widget_id}.css")
                with open(css_path, "w") as f:
                    f.write(css_code)

            created_at = datetime.now(timezone.utc).isoformat()
            base_description = None
            if base_metadata:
                base_description = base_metadata.get("description")
                if not base_description:
                    mcp_metadata = base_metadata.get("mcp")
                    if isinstance(mcp_metadata, dict):
                        base_description = mcp_metadata.get("description")

            description = base_description or self._derive_widget_description(prompt)
            metadata = {
                "widget_id": widget_id,
                "prompt": prompt,
                "user_id": user_id,
                "model": "claude-sonnet-4-5-20250929",
                "has_css": has_css,
                "created_at": created_at,
                "description": description,
            }
            mcp_payload = self._build_mcp_payload(widget_id, metadata)
            if mcp_payload:
                metadata["mcp"] = mcp_payload

            metadata_path = os.path.join(widget_assets_dir, f"{widget_id}.metadata.json")
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info(
                "Widget generated successfully",
                widget_id=widget_id,
                jsx_path=jsx_path,
                css_path=css_path,
            )

            # Build the widget
            await self._build_widget(widget_id)

            # Sync widget instructions to Langflow system prompt
            await self._sync_widgets_to_flow_prompt()

            return {
                "status": "success",
                "widget_id": widget_id,
                "jsx_path": jsx_path,
                "css_path": css_path,
                "metadata": metadata,
            }

        except Exception as e:
            logger.error("Widget generation failed", error=str(e), widget_id=widget_id)
            raise

    def _extract_code_block(self, text: str, *languages: str) -> str | None:
        """Extract code block from markdown response."""
        for lang in languages:
            start_marker = f"```{lang}"
            if start_marker in text:
                start = text.find(start_marker) + len(start_marker)
                end = text.find("```", start)
                if end != -1:
                    return text[start:end].strip()
        return None

    def _normalize_widget_css_import(self, jsx_code: str, widget_id: str, has_css: bool) -> str:
        """Ensure generated JSX references the correct widget CSS file."""
        lines = jsx_code.splitlines()
        css_import_indices: list[int] = []

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import") and ".css" in stripped:
                css_import_indices.append(idx)

        css_import_statement = f'import "./{widget_id}.css";'

        if has_css:
            if css_import_indices:
                first_idx = css_import_indices[0]
                lines[first_idx] = css_import_statement
                # Remove any additional css imports to prevent stale references
                for idx in reversed(css_import_indices[1:]):
                    lines.pop(idx)
            else:
                insert_idx = 0
                while insert_idx < len(lines) and lines[insert_idx].strip().startswith("import"):
                    insert_idx += 1
                lines.insert(insert_idx, css_import_statement)
        else:
            for idx in reversed(css_import_indices):
                lines.pop(idx)

        return "\n".join(lines)

    # TODO: Enforce per-user scoping when listing widgets to support multi-tenancy.
    async def list_widgets(self, user_id: str) -> list[Dict[str, Any]]:
        """List all widgets for a user."""
        try:
            widgets = []
            assets_dir = os.path.join(self.widgets_dir, "assets")
            if not os.path.exists(assets_dir):
                return widgets

            # Find all widget subdirectories
            for widget_id in os.listdir(assets_dir):
                widget_path = os.path.join(assets_dir, widget_id)
                if os.path.isdir(widget_path):
                    metadata = self._load_widget_metadata(widget_id, register=False)
                    if metadata:
                        widgets.append(metadata)
            return widgets
        except Exception as e:
            logger.error("Failed to list widgets", error=str(e))
            return []

    async def get_widget(self, widget_id: str) -> Dict[str, Any] | None:
        """Get widget details by ID."""
        try:
            metadata = self._load_widget_metadata(widget_id, register=False)
            if not metadata:
                return None
            widget_assets_dir = os.path.join(self.widgets_dir, "assets", widget_id)
            jsx_path = os.path.join(widget_assets_dir, f"{widget_id}.jsx")
            with open(jsx_path, "r") as f:
                jsx_content = f.read()
            css_path = os.path.join(widget_assets_dir, f"{widget_id}.css")
            css_content = None
            if os.path.exists(css_path):
                with open(css_path, "r") as f:
                    css_content = f.read()
            return {"metadata": metadata, "jsx_content": jsx_content, "css_content": css_content}
        except Exception as e:
            logger.error("Failed to get widget", error=str(e), widget_id=widget_id)
            return None

    async def delete_widget(self, widget_id: str, user_id: str) -> bool:
        """Delete a widget."""
        try:
            widget_assets_dir = os.path.join(self.widgets_dir, "assets", widget_id)

            # Delete the entire widget directory
            if os.path.exists(widget_assets_dir):
                import shutil
                shutil.rmtree(widget_assets_dir)

            logger.info("Widget deleted", widget_id=widget_id, user_id=user_id)
            if self._mcp_server:
                self._mcp_server.remove_widget(widget_id)

            # Sync widget instructions to Langflow system prompt
            await self._sync_widgets_to_flow_prompt()

            return True
        except Exception as e:
            logger.error("Failed to delete widget", error=str(e), widget_id=widget_id)
            return False

    async def rename_widget(self, widget_id: str, title: str, user_id: str) -> bool:
        """Rename a widget by updating its title in metadata."""
        try:
            widget_assets_dir = os.path.join(self.widgets_dir, "assets", widget_id)
            metadata_path = os.path.join(widget_assets_dir, f"{widget_id}.metadata.json")

            if not os.path.exists(metadata_path):
                return False

            # Load current metadata
            with open(metadata_path, "r") as f:
                metadata = json.load(f)

            # Update title in metadata
            metadata["title"] = title

            # Update MCP payload with new title
            if "mcp" in metadata:
                metadata["mcp"]["title"] = title
                metadata["mcp"]["invoking"] = f"Rendering {title}"
                metadata["mcp"]["invoked"] = f"{title} ready"
                metadata["mcp"]["response_text"] = f"Rendered {title}!"

            # Save updated metadata
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info("Widget renamed", widget_id=widget_id, title=title, user_id=user_id)

            # Update MCP server if available
            if self._mcp_server and "mcp" in metadata:
                self._mcp_server.upsert_widget(metadata["mcp"])

            return True
        except Exception as e:
            logger.error("Failed to rename widget", error=str(e), widget_id=widget_id)
            return False

    def _ensure_metadata_defaults(self, widget_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Populate metadata defaults such as created_at and persist if backfilled."""
        widget_assets_dir = os.path.join(self.widgets_dir, "assets", widget_id)
        metadata_path = os.path.join(widget_assets_dir, f"{widget_id}.metadata.json")

        if "created_at" not in metadata:
            try:
                created_ts = os.path.getmtime(metadata_path)
                metadata["created_at"] = datetime.fromtimestamp(
                    created_ts, tz=timezone.utc
                ).isoformat()
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f, indent=2)
            except Exception as e:
                logger.warning(
                    "Failed to backfill widget metadata",
                    error=str(e),
                    widget_id=widget_id,
                )
        if "description" not in metadata:
            description = self._derive_widget_description(metadata.get("prompt"))
            if description:
                metadata["description"] = description
                try:
                    with open(metadata_path, "w") as f:
                        json.dump(metadata, f, indent=2)
                except Exception as e:
                    logger.warning(
                        "Failed to persist widget description",
                        error=str(e),
                        widget_id=widget_id,
                    )
        return metadata

    def _derive_widget_title(self, prompt: str | None, widget_id: str) -> str:
        """Create a human-friendly title from the widget prompt or fallback to the id."""
        if prompt:
            first_line = prompt.strip().splitlines()[0]
            if first_line:
                trimmed = first_line[:60].rstrip()
                if len(first_line) > 60:
                    trimmed = f"{trimmed.rstrip()}..."
                return trimmed
        return f"Widget {widget_id[:8]}"

    def _derive_widget_description(self, prompt: str | None) -> str | None:
        """Create a concise description for the widget."""
        if not prompt:
            return None
        first_line = prompt.strip().splitlines()[0]
        if len(first_line) > 120:
            return first_line[:117].rstrip() + "..."
        return first_line

    def _build_mcp_payload(
        self,
        widget_id: str,
        metadata: Dict[str, Any],
        *,
        register: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Create MCP metadata for a widget and optionally sync it with the MCP server."""
        existing = metadata.get("mcp") or {}
        try:
            prompt = metadata.get("prompt")
            has_css = metadata.get("has_css", False)

            title = existing.get("title") or metadata.get("title") or self._derive_widget_title(
                prompt, widget_id
            )
            identifier = existing.get("identifier") or metadata.get("identifier") or widget_id
            template_uri = (
                existing.get("template_uri")
                or metadata.get("template_uri")
                or f"ui://widget/openrag-{widget_id}.html"
            )
            invoking = existing.get("invoking") or metadata.get("invoking") or f"Rendering {title}"
            invoked = existing.get("invoked") or metadata.get("invoked") or f"{title} ready"
            response_text = (
                existing.get("response_text")
                or metadata.get("response_text")
                or f"Rendered {title}!"
            )
            description = (
                existing.get("description")
                or metadata.get("description")
                or self._derive_widget_description(prompt)
            )

            payload = {
                "widget_id": widget_id,
                "identifier": identifier,
                "title": title,
                "template_uri": template_uri,
                "invoking": invoking,
                "invoked": invoked,
                "response_text": response_text,
                "has_css": has_css,
                "description": description,
            }

            if register:
                self._register_mcp_widget(payload)

            return payload
        except Exception as e:
            logger.error("Failed to prepare MCP payload", error=str(e), widget_id=widget_id)
            return existing if existing else None

    def _register_mcp_widget(self, payload: Dict[str, Any]) -> None:
        """Register or update a widget on the MCP server."""
        if self._mcp_server:
            self._mcp_server.upsert_widget(payload)

    def _refresh_mcp_registry(self) -> None:
        """Ensure the MCP server reflects the widgets stored on disk."""
        if not getattr(self, "_mcp_server", None):
            return

        payloads: List[Dict[str, Any]] = []
        assets_dir = os.path.join(self.widgets_dir, "assets")
        if os.path.exists(assets_dir):
            # Find all widget subdirectories
            for widget_id in os.listdir(assets_dir):
                widget_path = os.path.join(assets_dir, widget_id)
                if os.path.isdir(widget_path):
                    metadata = self._load_widget_metadata(widget_id, register=False)
                    if metadata and metadata.get("mcp"):
                        payloads.append(metadata["mcp"])

        self._mcp_server.replace_widgets(payloads)

    def attach_mcp_server(self, mcp_server: "WidgetMCPServer") -> None:
        """Attach an MCP server after initialization and sync widgets."""
        self._mcp_server = mcp_server
        self._refresh_mcp_registry()

    def _load_widget_metadata(self, widget_id: str, register: bool = False) -> Optional[Dict[str, Any]]:
        """Load widget metadata from disk and populate MCP details."""
        widget_assets_dir = os.path.join(self.widgets_dir, "assets", widget_id)
        metadata_path = os.path.join(widget_assets_dir, f"{widget_id}.metadata.json")

        if not os.path.exists(metadata_path):
            return None

        with open(metadata_path, "r") as f:
            metadata = json.load(f)

        metadata = self._ensure_metadata_defaults(widget_id, metadata)
        payload = self._build_mcp_payload(widget_id, metadata, register=register)
        if payload:
            if metadata.get("mcp") != payload:
                metadata["mcp"] = payload
                try:
                    with open(metadata_path, "w") as f:
                        json.dump(metadata, f, indent=2)
                except Exception as e:
                    logger.warning(
                        "Failed to persist MCP metadata for widget",
                        error=str(e),
                        widget_id=widget_id,
                    )
        elif "mcp" in metadata:
            metadata.pop("mcp", None)

        return metadata

    def _check_build_dependencies(self):
        """Check if npm is available and install dependencies if needed."""
        try:
            subprocess.run(
                ["npm", "--version"],
                capture_output=True,
                check=True,
                cwd=self.widgets_dir
            )
            logger.info("npm is available for widget building")

            # Check if node_modules exists, if not install
            node_modules = os.path.join(self.widgets_dir, "node_modules")
            if not os.path.exists(node_modules):
                logger.info("Widget dependencies not installed. Starting background installation...")
                with self._dependency_install_lock:
                    if not self._install_task_started:
                        self._install_task_started = True
                        threading.Thread(
                            target=self._install_dependencies,
                            name="widget-npm-install",
                            daemon=True,
                        ).start()
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning(
                "npm not found. Widget building will be disabled. Install Node.js to enable widget building."
            )

    def _install_dependencies(self):
        """Install widget npm dependencies in a background thread."""
        try:
            result = subprocess.run(
                ["npm", "install"],
                cwd=self.widgets_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
            if result.returncode == 0:
                logger.info("Widget dependencies installed successfully")
            else:
                logger.error("Failed to install widget dependencies", error=result.stderr)
        except subprocess.TimeoutExpired:
            logger.error("npm install timed out after 300 seconds")
        except Exception as e:
            logger.error("Failed to install widget dependencies", error=str(e))
        finally:
            with self._dependency_install_lock:
                self._install_task_started = False

    async def _build_widget(self, widget_id: str):
        """Build a widget using Vite."""
        try:
            logger.info("Building widget", widget_id=widget_id)

            # Check if node_modules exists
            node_modules = os.path.join(self.widgets_dir, "node_modules")
            if not os.path.exists(node_modules):
                if self._install_task_started:
                    logger.info(
                        "Widget build postponed while dependencies install in background",
                        widget_id=widget_id,
                    )
                else:
                    logger.error(
                        "Cannot build widget: dependencies not installed. Run 'cd widgets && npm install'"
                    )
                return

            # Run npm build in the widgets directory
            process = await asyncio.create_subprocess_exec(
                "npm", "run", "build",
                cwd=self.widgets_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(
                    "Widget built successfully",
                    widget_id=widget_id,
                    output=stdout.decode()[:200]
                )
            else:
                logger.error(
                    "Widget build failed",
                    widget_id=widget_id,
                    error=stderr.decode()
                )

        except Exception as e:
            logger.error("Failed to build widget", error=str(e), widget_id=widget_id)
