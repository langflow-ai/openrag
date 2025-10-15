"""Widget generation service using Claude Agent SDK."""
import os
import json
import subprocess
import asyncio
import threading
from datetime import datetime, timezone
from typing import Dict, Any
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Claude Agent SDK imports
try:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
except ImportError:
    raise ImportError(
        "Claude Agent SDK not installed. Please install with: pip install claude-agent-sdk"
    )


class WidgetService:
    """Service for generating React widget components using Claude Agent SDK."""

    def __init__(self):
        self.widgets_dir = os.path.abspath("widgets")
        self.assets_dir = os.path.join(self.widgets_dir, "assets")
        os.makedirs(self.widgets_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)
        logger.info("Widget service initialized", widgets_dir=self.widgets_dir)
        self._dependency_install_lock = threading.Lock()
        self._install_task_started = False

        # Check if npm and vite are available
        self._check_build_dependencies()

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
            if base_widget_id:
                base_widget = await self.get_widget(base_widget_id)
                if base_widget:
                    base_jsx = base_widget.get("jsx_content")
                    base_css = base_widget.get("css_content")
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
                model="claude-3-5-sonnet-20241022",
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

            if not jsx_code:
                raise Exception("No JSX code block found in response")

            # Write files
            widget_dir = os.path.join(self.widgets_dir, widget_id)
            os.makedirs(widget_dir, exist_ok=True)

            jsx_path = os.path.join(widget_dir, f"{widget_id}.jsx")
            with open(jsx_path, "w") as f:
                f.write(jsx_code)

            css_path = None
            if css_code:
                css_path = os.path.join(widget_dir, f"{widget_id}.css")
                with open(css_path, "w") as f:
                    f.write(css_code)

            created_at = datetime.now(timezone.utc).isoformat()
            metadata = {
                "widget_id": widget_id,
                "prompt": prompt,
                "user_id": user_id,
                "model": "claude-3-5-sonnet-20241022",
                "has_css": css_code is not None,
                "created_at": created_at,
            }
            metadata_path = os.path.join(widget_dir, "metadata.json")
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

    # TODO: Enforce per-user scoping when listing widgets to support multi-tenancy.
    async def list_widgets(self, user_id: str) -> list[Dict[str, Any]]:
        """List all widgets for a user."""
        try:
            widgets = []
            if not os.path.exists(self.widgets_dir):
                return widgets

            for widget_id in os.listdir(self.widgets_dir):
                widget_path = os.path.join(self.widgets_dir, widget_id)
                if not os.path.isdir(widget_path):
                    continue
                metadata_path = os.path.join(widget_path, "metadata.json")
                if os.path.exists(metadata_path):
                    with open(metadata_path, "r") as f:
                        metadata = json.load(f)
                        metadata = self._ensure_metadata_defaults(widget_path, metadata)
                        widgets.append(metadata)
            return widgets
        except Exception as e:
            logger.error("Failed to list widgets", error=str(e))
            return []

    async def get_widget(self, widget_id: str) -> Dict[str, Any] | None:
        """Get widget details by ID."""
        try:
            widget_path = os.path.join(self.widgets_dir, widget_id)
            if not os.path.exists(widget_path):
                return None
            metadata_path = os.path.join(widget_path, "metadata.json")
            if not os.path.exists(metadata_path):
                return None

            with open(metadata_path, "r") as f:
                metadata = json.load(f)
                metadata = self._ensure_metadata_defaults(widget_path, metadata)
            jsx_path = os.path.join(widget_path, f"{widget_id}.jsx")
            with open(jsx_path, "r") as f:
                jsx_content = f.read()
            css_path = os.path.join(widget_path, f"{widget_id}.css")
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
            widget_path = os.path.join(self.widgets_dir, widget_id)
            if not os.path.exists(widget_path):
                return False
            import shutil
            shutil.rmtree(widget_path)

            # Also delete built assets
            js_asset = os.path.join(self.assets_dir, f"{widget_id}.js")
            css_asset = os.path.join(self.assets_dir, f"{widget_id}.css")
            if os.path.exists(js_asset):
                os.remove(js_asset)
            if os.path.exists(css_asset):
                os.remove(css_asset)

            logger.info("Widget deleted", widget_id=widget_id, user_id=user_id)
            return True
        except Exception as e:
            logger.error("Failed to delete widget", error=str(e), widget_id=widget_id)
            return False

    def _ensure_metadata_defaults(self, widget_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Populate metadata defaults such as created_at and persist if backfilled."""
        if "created_at" not in metadata:
            try:
                created_ts = os.path.getmtime(widget_path)
                metadata["created_at"] = datetime.fromtimestamp(
                    created_ts, tz=timezone.utc
                ).isoformat()
                metadata_path = os.path.join(widget_path, "metadata.json")
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f, indent=2)
            except Exception as e:
                logger.warning(
                    "Failed to backfill widget metadata",
                    error=str(e),
                    widget_path=widget_path,
                )
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
