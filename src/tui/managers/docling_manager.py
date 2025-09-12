"""Docling serve manager for local document processing service."""

import asyncio
import threading
import time
from typing import Optional, Tuple, Dict, Any
import uvicorn
from utils.logging_config import get_logger

logger = get_logger(__name__)


class DoclingManager:
    """Manages local docling serve instance running in-process."""

    def __init__(self):
        self._server: Optional[uvicorn.Server] = None
        self._server_thread: Optional[threading.Thread] = None
        self._port = 5001
        self._host = "127.0.0.1"
        self._running = False
        
    def is_running(self) -> bool:
        """Check if docling serve is running."""
        return self._running and self._server_thread is not None and self._server_thread.is_alive()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of docling serve."""
        if self.is_running():
            return {
                "status": "running",
                "port": self._port,
                "host": self._host,
                "endpoint": f"http://{self._host}:{self._port}",
                "docs_url": f"http://{self._host}:{self._port}/docs",
                "ui_url": f"http://{self._host}:{self._port}/ui"
            }
        else:
            return {
                "status": "stopped",
                "port": self._port,
                "host": self._host,
                "endpoint": None,
                "docs_url": None,
                "ui_url": None
            }
    
    async def start(self, port: int = 5001, host: str = "127.0.0.1", enable_ui: bool = True) -> Tuple[bool, str]:
        """Start docling serve in a separate thread."""
        if self.is_running():
            return False, "Docling serve is already running"
        
        self._port = port
        self._host = host
        
        try:
            logger.info(f"Starting docling serve on {host}:{port}")
            
            # Import and create the FastAPI app
            from docling_serve.app import create_app
            from docling_serve.settings import docling_serve_settings
            
            # Configure settings
            docling_serve_settings.enable_ui = enable_ui
            
            # Create the FastAPI app
            app = create_app()
            
            # Create uvicorn server configuration
            config = uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_level="info",
                access_log=False,  # Reduce noise in TUI
            )
            
            self._server = uvicorn.Server(config)
            
            # Start server in a separate thread
            self._server_thread = threading.Thread(
                target=self._run_server,
                name="docling-serve-thread",
                daemon=True  # Dies when main thread dies
            )
            
            self._running = True
            self._server_thread.start()
            
            # Wait a moment to see if it starts successfully
            await asyncio.sleep(2)
            
            if not self._server_thread.is_alive():
                self._running = False
                self._server = None
                self._server_thread = None
                return False, "Failed to start docling serve thread"
            
            logger.info(f"Docling serve started successfully on {host}:{port}")
            return True, f"Docling serve started on http://{host}:{port}"
            
        except ImportError as e:
            logger.error(f"Failed to import docling_serve: {e}")
            return False, "docling-serve not available. Please install: uv add docling-serve"
        except Exception as e:
            logger.error(f"Error starting docling serve: {e}")
            self._running = False
            self._server = None
            self._server_thread = None
            return False, f"Error starting docling serve: {str(e)}"
    
    def _run_server(self):
        """Run the uvicorn server in the current thread."""
        try:
            logger.info("Starting uvicorn server in thread")
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the server
            loop.run_until_complete(self._server.serve())
        except Exception as e:
            logger.error(f"Error in server thread: {e}")
        finally:
            self._running = False
            logger.info("Server thread stopped")
    
    async def stop(self) -> Tuple[bool, str]:
        """Stop docling serve."""
        if not self.is_running():
            return False, "Docling serve is not running"
        
        try:
            logger.info("Stopping docling serve")
            
            # Signal the server to shut down
            if self._server:
                self._server.should_exit = True
            
            self._running = False
            
            # Wait for the thread to finish (with timeout)
            if self._server_thread:
                self._server_thread.join(timeout=10)
                
                if self._server_thread.is_alive():
                    logger.warning("Server thread did not stop gracefully")
                    return False, "Docling serve did not stop gracefully"
            
            self._server = None
            self._server_thread = None
            
            logger.info("Docling serve stopped")
            return True, "Docling serve stopped successfully"
            
        except Exception as e:
            logger.error(f"Error stopping docling serve: {e}")
            return False, f"Error stopping docling serve: {str(e)}"
    
    async def restart(self, port: int = None, host: str = None, enable_ui: bool = True) -> Tuple[bool, str]:
        """Restart docling serve."""
        # Use current settings if not specified
        if port is None:
            port = self._port
        if host is None:
            host = self._host
            
        # Stop if running
        if self.is_running():
            success, msg = await self.stop()
            if not success:
                return False, f"Failed to stop: {msg}"
            
            # Wait a moment for cleanup
            await asyncio.sleep(1)
        
        # Start with new settings
        return await self.start(port, host, enable_ui)
    
    def get_logs(self, lines: int = 50) -> Tuple[bool, str]:
        """Get basic status info (no historical logs available for in-process server)."""
        if not self.is_running():
            return False, "Docling serve is not running"
        
        try:
            status = self.get_status()
            log_info = [
                f"Docling serve is running on {status['endpoint']}",
                f"Documentation: {status['docs_url']}",
            ]
            
            if status.get('ui_url'):
                log_info.append(f"UI: {status['ui_url']}")
            
            log_info.append(f"Thread alive: {self._server_thread.is_alive() if self._server_thread else False}")
            
            return True, "\n".join(log_info)
        except Exception as e:
            return False, f"Error getting status: {str(e)}"