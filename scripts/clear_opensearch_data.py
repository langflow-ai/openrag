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

    # Get opensearch data path from env config (same as container_manager uses)
    from src.tui.managers.env_manager import EnvManager
    env_manager = EnvManager()
    env_manager.load_existing_env()
    opensearch_data_path = Path(
        env_manager.config.opensearch_data_path.replace("$HOME", str(Path.home()))
    ).expanduser()

    if not opensearch_data_path.exists():
        print(f"opensearch-data directory does not exist at {opensearch_data_path}")
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
