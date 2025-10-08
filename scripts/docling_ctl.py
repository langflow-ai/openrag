#!/usr/bin/env python3
"""Helper script to control docling-serve using DoclingManager for CI/testing."""

import sys
import asyncio
import argparse
from pathlib import Path

# Add src to path so we can import DoclingManager
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tui.managers.docling_manager import DoclingManager


async def start_docling(port: int = 5001, host: str = None, enable_ui: bool = False):
    """Start docling-serve."""
    manager = DoclingManager()

    if manager.is_running():
        print(f"Docling-serve is already running")
        status = manager.get_status()
        print(f"Endpoint: {status['endpoint']}")
        return 0

    host_msg = f"{host}:{port}" if host else f"auto-detected host:{port}"
    print(f"Starting docling-serve on {host_msg}...")
    success, message = await manager.start(port=port, host=host, enable_ui=enable_ui)

    if success:
        print(f"{message}")
        status = manager.get_status()
        print(f"Endpoint: {status['endpoint']}")
        print(f"PID: {status['pid']}")
        return 0
    else:
        print(f"{message}", file=sys.stderr)
        return 1


async def stop_docling():
    """Stop docling-serve."""
    manager = DoclingManager()

    if not manager.is_running():
        print("Docling-serve is not running")
        return 0

    print("Stopping docling-serve...")
    success, message = await manager.stop()

    if success:
        print(f"{message}")
        return 0
    else:
        print(f"{message}", file=sys.stderr)
        return 1


async def status_docling():
    """Get docling-serve status."""
    manager = DoclingManager()
    status = manager.get_status()

    print(f"Status: {status['status']}")
    if status['status'] == 'running':
        print(f"Endpoint: {status['endpoint']}")
        print(f"Docs: {status['docs_url']}")
        print(f"PID: {status['pid']}")

    return 0 if status['status'] == 'running' else 1


async def main():
    parser = argparse.ArgumentParser(description="Control docling-serve for CI/testing")
    parser.add_argument("command", choices=["start", "stop", "status"], help="Command to run")
    parser.add_argument("--port", type=int, default=5001, help="Port to run on (default: 5001)")
    parser.add_argument("--host", default=None, help="Host to bind to (default: auto-detect for containers)")
    parser.add_argument("--enable-ui", action="store_true", help="Enable UI")

    args = parser.parse_args()

    if args.command == "start":
        return await start_docling(port=args.port, host=args.host if args.host else None, enable_ui=args.enable_ui)
    elif args.command == "stop":
        return await stop_docling()
    elif args.command == "status":
        return await status_docling()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
