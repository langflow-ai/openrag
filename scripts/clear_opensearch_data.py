#!/usr/bin/env python3
"""Clear OpenSearch data directory using container with proper permissions."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tui.managers.container_manager import ContainerManager


async def main():
    """Clear OpenSearch data volume."""
    cm = ContainerManager()

    if not cm.is_available():
        print("Error: No container runtime available")
        return 1

    print("Clearing OpenSearch data volume...")

    async for success, message in cm.clear_opensearch_data_volume():
        print(message)
        if not success and "failed" in message.lower():
            return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
