#!/usr/bin/env python3
"""Clear OpenSearch data directory using container with proper permissions."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tui.managers.container_manager import ContainerManager


async def main():
    """Clear OpenSearch data directory."""
    cm = ContainerManager()
    
    opensearch_data_path = Path("opensearch-data")
    if not opensearch_data_path.exists():
        print("opensearch-data directory does not exist")
        return 0
    
    print("Clearing OpenSearch data directory...")
    
    async for success, message in cm.clear_opensearch_data_volume():
        print(message)
        if not success and "failed" in message.lower():
            return 1
    
    print("✅ OpenSearch data cleared successfully")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
