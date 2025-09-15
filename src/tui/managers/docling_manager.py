"""Docling serve manager for local document processing service."""

import asyncio
import io
import queue
import sys
import threading
import time
from typing import Optional, Tuple, Dict, Any, List, AsyncIterator
import uvicorn
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LogCaptureHandler:
    """Custom handler to capture logs from docling-serve."""
    
    def __init__(self, log_queue: queue.Queue):
        self.log_queue = log_queue
        self.buffer = ""
        # Store original stdout for direct printing
        self.original_stdout = sys.__stdout__
        
    def write(self, message):
        if not message:
            return
            
        # Add to buffer and process complete lines
        self.buffer += message
        
        # Process complete lines
        if '\n' in self.buffer:
            lines = self.buffer.split('\n')
            # Keep the last incomplete line in the buffer
            self.buffer = lines.pop()
            
            # Process complete lines
            for line in lines:
                if line.strip():  # Skip empty lines
                    # Print directly to original stdout for debugging
                    print(f"[DOCLING] {line}", file=self.original_stdout)
                    self.log_queue.put(line)
        
        # If message ends with newline, process the buffer too
        elif message.endswith('\n') and self.buffer.strip():
            print(f"[DOCLING] {self.buffer.strip()}", file=self.original_stdout)
            self.log_queue.put(self.buffer.strip())
            self.buffer = ""
            
    def flush(self):
        # Process any remaining content in the buffer
        if self.buffer.strip():
            print(f"[DOCLING] {self.buffer.strip()}", file=self.original_stdout)
            self.log_queue.put(self.buffer.strip())
            self.buffer = ""


class DoclingManager:
    """Manages local docling serve instance running in-process."""

    def __init__(self):
        self._server: Optional[uvicorn.Server] = None
        self._server_thread: Optional[threading.Thread] = None
        self._port = 5001
        self._host = "127.0.0.1"
        self._running = False
        self._external_process = False
        
        # Log storage
        self._log_queue = queue.Queue()
        self._log_handler = LogCaptureHandler(self._log_queue)
        self._log_buffer: List[str] = []
        self._max_log_lines = 1000
        self._log_processor_running = False
        self._log_processor_thread = None
        
        # Start log processor thread
        self._start_log_processor()
        
        # Configure Python logging to capture docling-serve logs
        self._setup_logging_capture()
    
    def _setup_logging_capture(self):
        """Configure Python logging to capture docling-serve logs."""
        try:
            import logging
            
            # Create a handler that writes to our log queue
            class DoclingLogHandler(logging.Handler):
                def __init__(self, docling_manager):
                    super().__init__()
                    self.docling_manager = docling_manager
                    
                def emit(self, record):
                    msg = self.format(record)
                    self.docling_manager._add_log_entry(f"LOG: {msg}")
            
            # Configure root logger to capture all logs
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.DEBUG)
            
            # Add our handler
            handler = DoclingLogHandler(self)
            formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            root_logger.addHandler(handler)
            
            # Specifically configure uvicorn and docling_serve loggers
            for logger_name in ["uvicorn", "docling_serve", "fastapi"]:
                logger = logging.getLogger(logger_name)
                logger.setLevel(logging.DEBUG)
                # Make sure our handler is added
                if not any(isinstance(h, DoclingLogHandler) for h in logger.handlers):
                    logger.addHandler(handler)
            
            self._add_log_entry("Configured logging capture for docling-serve")
            
        except Exception as e:
            self._add_log_entry(f"Failed to configure logging capture: {e}")
    
    def _start_log_processor(self) -> None:
        """Start a thread to process logs from the queue."""
        if self._log_processor_running:
            return
            
        self._log_processor_running = True
        self._log_processor_thread = threading.Thread(
            target=self._process_logs,
            name="docling-log-processor",
            daemon=True
        )
        self._log_processor_thread.start()
        
    def _process_logs(self) -> None:
        """Process logs from the queue and add them to the buffer."""
        # Add a debug entry to confirm the processor started
        self._add_log_entry("Log processor started")
        logger.info("Docling log processor started")
        
        while True:
            try:
                # Get log message from queue with timeout
                try:
                    message = self._log_queue.get(timeout=0.5)
                    if message:
                        # Add to our buffer
                        self._add_log_entry(message.rstrip())
                    self._log_queue.task_done()
                except queue.Empty:
                    # No logs in queue, just continue
                    pass
                    
                # If we're not running and queue is empty, exit
                if not self._running and self._log_queue.empty():
                    time.sleep(1)  # Give a chance for final logs
                    if self._log_queue.empty():
                        break
                        
                # Brief pause to avoid CPU spinning
                time.sleep(0.01)
                
            except Exception as e:
                # Log the error but keep the processor running
                error_msg = f"Error processing logs: {e}"
                logger.error(error_msg)
                self._add_log_entry(f"ERROR: {error_msg}")
                time.sleep(1)  # Pause after error
                
        self._log_processor_running = False
        logger.info("Docling log processor stopped")
        
    def _add_log_entry(self, message: str) -> None:
        """Add a log entry to the buffer."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self._log_buffer.append(entry)
        
        # Keep buffer size limited
        if len(self._log_buffer) > self._max_log_lines:
            self._log_buffer = self._log_buffer[-self._max_log_lines:]
        
    def is_running(self) -> bool:
        """Check if docling serve is running."""
        # First check our internal state
        internal_running = self._running and self._server_thread is not None and self._server_thread.is_alive()
        
        # If we think it's not running, check if something is listening on the port
        # This handles cases where docling-serve was started outside the TUI
        if not internal_running:
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                result = s.connect_ex((self._host, self._port))
                s.close()
                
                # If port is in use, something is running there
                if result == 0:
                    # Add a log entry about this
                    self._add_log_entry(f"Detected external docling-serve running on {self._host}:{self._port}")
                    # Set a flag to indicate this is an external process
                    self._external_process = True
                    return True
            except Exception as e:
                # If there's an error checking, fall back to internal state
                logger.error(f"Error checking port: {e}")
        else:
            # If we started it, it's not external
            self._external_process = False
                
        return internal_running
    
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
        
        # Clear log buffer when starting
        self._log_buffer = []
        
        try:
            logger.info(f"Starting docling serve on {host}:{port}")
            
            # Import and create the FastAPI app
            from docling_serve.app import create_app
            from docling_serve.settings import docling_serve_settings
            
            # Configure settings
            docling_serve_settings.enable_ui = enable_ui
            
            # Enable verbose logging in docling-serve if possible
            try:
                import logging
                docling_logger = logging.getLogger("docling_serve")
                docling_logger.setLevel(logging.DEBUG)
                self._add_log_entry("Set docling_serve logger to DEBUG level")
            except Exception as e:
                self._add_log_entry(f"Failed to set docling_serve logger level: {e}")
            
            # Create the FastAPI app
            app = create_app()
            
            # Create uvicorn server configuration
            config = uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_level="debug",  # Use debug level for more verbose output
                access_log=True,    # Enable access logs
            )
            
            self._server = uvicorn.Server(config)
            
            # Add log entry
            self._add_log_entry(f"Starting docling-serve on {host}:{port}")
            
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
        # Save original stdout/stderr before any possible exceptions
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        
        try:
            logger.info("Starting uvicorn server in thread")
            
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Create temporary stdout/stderr handlers that don't use logging
            # to avoid recursion when logging tries to write to stdout
            class SimpleHandler:
                def __init__(self, prefix, queue):
                    self.prefix = prefix
                    self.queue = queue
                    self.original_stdout = sys.__stdout__
                    
                def write(self, message):
                    if message and message.strip():
                        # Print directly to original stdout for debugging
                        print(f"[{self.prefix}] {message.rstrip()}", file=self.original_stdout)
                        # Also add to queue for the log buffer
                        self.queue.put(f"{self.prefix}: {message.rstrip()}")
                        
                def flush(self):
                    pass
            
            # Add a test message to the log queue
            self._add_log_entry("Starting docling-serve with improved logging")
            self._log_queue.put("TEST: Direct message to queue before redirection")
            
            # Create simple handlers
            stdout_simple = SimpleHandler("STDOUT", self._log_queue)
            stderr_simple = SimpleHandler("STDERR", self._log_queue)
            
            # Redirect stdout/stderr to our simple handlers
            sys.stdout = stdout_simple
            sys.stderr = stderr_simple
            
            # Test if redirection works
            print("TEST: Print after redirection in _run_server")
            sys.stderr.write("TEST: stderr write after redirection\n")
            
            # Add log entry
            self._add_log_entry("Docling serve starting")
            
            # Run the server
            if self._server:
                self._add_log_entry("Starting server.serve()")
                logger.info("About to run server.serve()")
                
                # Configure Python logging to capture uvicorn logs
                try:
                    import logging
                    
                    # Create a handler that writes to our log queue
                    class DoclingLogHandler(logging.Handler):
                        def __init__(self, queue):
                            super().__init__()
                            self.queue = queue
                            
                        def emit(self, record):
                            msg = self.format(record)
                            self.queue.put(f"LOG: {msg}")
                    
                    # Configure uvicorn logger
                    uvicorn_logger = logging.getLogger("uvicorn")
                    uvicorn_logger.setLevel(logging.DEBUG)
                    
                    # Add our handler
                    handler = DoclingLogHandler(self._log_queue)
                    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
                    handler.setFormatter(formatter)
                    uvicorn_logger.addHandler(handler)
                    
                    self._add_log_entry("Added custom handler to uvicorn logger")
                except Exception as e:
                    self._add_log_entry(f"Failed to configure uvicorn logger: {e}")
                
                loop.run_until_complete(self._server.serve())
                self._add_log_entry("server.serve() completed")
            else:
                self._add_log_entry("Error: Server not initialized")
                
        except Exception as e:
            error_msg = f"Error in server thread: {e}"
            logger.error(error_msg)
            self._add_log_entry(error_msg)
        finally:
            # Add log entry before restoring stdout/stderr
            self._add_log_entry("Restoring stdout/stderr")
            
            # Restore stdout/stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            
            logger.info("Stdout/stderr restored")
            
            self._running = False
            self._add_log_entry("Docling serve stopped")
            logger.info("Server thread stopped")
    
    async def stop(self) -> Tuple[bool, str]:
        """Stop docling serve."""
        if not self.is_running():
            return False, "Docling serve is not running"
        
        try:
            logger.info("Stopping docling serve")
            
            # Add a log entry before stopping
            self._add_log_entry("Stopping docling-serve via API call")
            
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
    
    async def restart(self, port: Optional[int] = None, host: Optional[str] = None, enable_ui: bool = True) -> Tuple[bool, str]:
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
    
    def add_manual_log_entry(self, message: str) -> None:
        """Add a manual log entry - useful for debugging."""
        self._add_log_entry(f"MANUAL: {message}")
    
    def get_logs(self, lines: int = 50) -> Tuple[bool, str]:
        """Get logs from the docling-serve process."""
        if self.is_running():
            # Create a status message but don't add it to the log buffer
            status_msg = f"Docling serve is running on http://{self._host}:{self._port}"
            
            # If we have no logs but the service is running, it might have been started externally
            if not self._log_buffer:
                # Return informative message without modifying the log buffer
                return True, (
                    f"{status_msg}\n\n"
                    "No logs available - service may have been started externally.\n"
                    "You can restart the service from the Monitor screen to capture logs."
                )
                
            # Return the most recent logs with status message at the top
            log_count = min(lines, len(self._log_buffer))
            logs = "\n".join(self._log_buffer[-log_count:])
            return True, f"{status_msg}\n\n{logs}"
        else:
            # Return success with a message instead of an error
            # This allows viewing the message without an error notification
            return True, "Docling serve is not running. Start it from the Monitor screen to view logs."
    
    async def follow_logs(self) -> AsyncIterator[str]:
        """Follow logs from the docling-serve process in real-time."""
        # First yield status message and any existing logs
        status_msg = f"Docling serve is running on http://{self._host}:{self._port}"
        
        if self._log_buffer:
            yield f"{status_msg}\n\n" + "\n".join(self._log_buffer)
        else:
            yield (
                f"{status_msg}\n\n"
                "Waiting for logs...\n"
                "If no logs appear, the service may have been started externally.\n"
                "You can restart the service from the Monitor screen to capture logs."
            )
        
        # Then start monitoring for new logs
        last_log_index = len(self._log_buffer)
        
        while self.is_running():
            # Check if we have new logs
            if len(self._log_buffer) > last_log_index:
                # Yield only the new logs
                new_logs = self._log_buffer[last_log_index:]
                yield "\n".join(new_logs)
                last_log_index = len(self._log_buffer)
            
            # Wait a bit before checking again
            await asyncio.sleep(0.1)
        
        # Final check for any logs that came in during shutdown
        if len(self._log_buffer) > last_log_index:
            yield "\n".join(self._log_buffer[last_log_index:])
