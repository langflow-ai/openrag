"""Docling serve manager for local document processing service."""

import asyncio
import os
import subprocess
import sys
import threading
import time
from typing import Optional, Tuple, Dict, Any, List, AsyncIterator
from utils.logging_config import get_logger

logger = get_logger(__name__)



class DoclingManager:
    """Manages local docling serve instance as external process."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if self._initialized:
            return

        self._process: Optional[subprocess.Popen] = None
        self._port = 5001
        self._host = "127.0.0.1"
        self._running = False
        self._external_process = False

        # Log storage - simplified, no queue
        self._log_buffer: List[str] = []
        self._max_log_lines = 1000
        self._log_lock = threading.Lock()  # Thread-safe access to log buffer

        self._initialized = True

    def cleanup(self):
        """Cleanup resources and stop any running processes."""
        if self._process and self._process.poll() is None:
            self._add_log_entry("Cleaning up docling-serve process on exit")
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            except Exception as e:
                self._add_log_entry(f"Error during cleanup: {e}")

        self._running = False
        self._process = None
        
    def _add_log_entry(self, message: str) -> None:
        """Add a log entry to the buffer (thread-safe)."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}"

        with self._log_lock:
            self._log_buffer.append(entry)
            # Keep buffer size limited
            if len(self._log_buffer) > self._max_log_lines:
                self._log_buffer = self._log_buffer[-self._max_log_lines:]
        
    def is_running(self) -> bool:
        """Check if docling serve is running."""
        # First check our internal state
        internal_running = self._running and self._process is not None and self._process.poll() is None

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
                    # Only log this once when we first detect external process
                    if not self._external_process:
                        self._add_log_entry(f"Detected external docling-serve running on {self._host}:{self._port}")
                    # Set a flag to indicate this is an external process
                    self._external_process = True
                    return True
            except Exception as e:
                # Only log errors occasionally to avoid spam
                if not hasattr(self, '_last_port_error') or self._last_port_error != str(e):
                    self._add_log_entry(f"Error checking port: {e}")
                    self._last_port_error = str(e)
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
        """Start docling serve as external process."""
        if self.is_running():
            return False, "Docling serve is already running"

        self._port = port
        self._host = host

        # Clear log buffer when starting
        self._log_buffer = []
        self._add_log_entry("Starting docling serve as external process...")

        try:
            # Build command to run docling-serve
            # Check if we should use uv run (look for uv in environment or check if we're in a uv project)
            import shutil
            if shutil.which("uv") and (os.path.exists("pyproject.toml") or os.getenv("VIRTUAL_ENV")):
                cmd = [
                    "uv", "run", "python", "-m", "docling_serve", "run",
                    "--host", host,
                    "--port", str(port),
                ]
            else:
                cmd = [
                    sys.executable, "-m", "docling_serve", "run",
                    "--host", host,
                    "--port", str(port),
                ]

            if enable_ui:
                cmd.append("--enable-ui")

            self._add_log_entry(f"Starting process: {' '.join(cmd)}")

            # Start as subprocess
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=0  # Unbuffered for real-time output
            )

            self._running = True
            self._add_log_entry("External process started")

            # Start a thread to capture output
            self._start_output_capture()

            # Wait for the process to start and begin listening
            self._add_log_entry("Waiting for docling-serve to start listening...")

            # Wait up to 10 seconds for the service to start listening
            for i in range(10):
                await asyncio.sleep(1.0)

                # Check if process is still alive
                if self._process.poll() is not None:
                    break

                # Check if it's listening on the port
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.5)
                    result = s.connect_ex((host, port))
                    s.close()

                    if result == 0:
                        self._add_log_entry(f"Docling-serve is now listening on {host}:{port}")
                        break
                except:
                    pass

                self._add_log_entry(f"Waiting for startup... ({i+1}/10)")

            # Add a test message to verify logging is working
            self._add_log_entry(f"Process PID: {self._process.pid}, Poll: {self._process.poll()}")

            if self._process.poll() is not None:
                # Process already exited - get return code and any output
                return_code = self._process.returncode
                self._add_log_entry(f"Process exited with code: {return_code}")

                try:
                    # Try to read any remaining output
                    stdout_data = ""
                    stderr_data = ""

                    if self._process.stdout:
                        stdout_data = self._process.stdout.read()
                    if self._process.stderr:
                        stderr_data = self._process.stderr.read()

                    if stdout_data:
                        self._add_log_entry(f"Final stdout: {stdout_data[:500]}")
                    if stderr_data:
                        self._add_log_entry(f"Final stderr: {stderr_data[:500]}")

                except Exception as e:
                    self._add_log_entry(f"Error reading final output: {e}")

                self._running = False
                return False, f"Docling serve process exited immediately (code: {return_code})"

            return True, f"Docling serve starting on http://{host}:{port}"

        except FileNotFoundError:
            return False, "docling-serve not available. Please install: uv add docling-serve"
        except Exception as e:
            self._running = False
            self._process = None
            return False, f"Error starting docling serve: {str(e)}"

    def _start_output_capture(self):
        """Start threads to capture subprocess stdout and stderr."""
        def capture_stdout():
            if not self._process or not self._process.stdout:
                self._add_log_entry("No stdout pipe available")
                return

            self._add_log_entry("Starting stdout capture thread")
            try:
                while self._running and self._process and self._process.poll() is None:
                    line = self._process.stdout.readline()
                    if line:
                        self._add_log_entry(f"STDOUT: {line.rstrip()}")
                    else:
                        # No more output, wait a bit
                        time.sleep(0.1)
            except Exception as e:
                self._add_log_entry(f"Error capturing stdout: {e}")
            finally:
                self._add_log_entry("Stdout capture thread ended")

        def capture_stderr():
            if not self._process or not self._process.stderr:
                self._add_log_entry("No stderr pipe available")
                return

            self._add_log_entry("Starting stderr capture thread")
            try:
                while self._running and self._process and self._process.poll() is None:
                    line = self._process.stderr.readline()
                    if line:
                        self._add_log_entry(f"STDERR: {line.rstrip()}")
                    else:
                        # No more output, wait a bit
                        time.sleep(0.1)
            except Exception as e:
                self._add_log_entry(f"Error capturing stderr: {e}")
            finally:
                self._add_log_entry("Stderr capture thread ended")

        # Start both capture threads
        stdout_thread = threading.Thread(target=capture_stdout, daemon=True)
        stderr_thread = threading.Thread(target=capture_stderr, daemon=True)

        stdout_thread.start()
        stderr_thread.start()

        self._add_log_entry("Output capture threads started")

    async def stop(self) -> Tuple[bool, str]:
        """Stop docling serve."""
        if not self.is_running():
            return False, "Docling serve is not running"

        try:
            self._add_log_entry("Stopping docling-serve process")

            if self._process:
                # We started this process, so we can stop it directly
                self._add_log_entry(f"Terminating our process (PID: {self._process.pid})")
                self._process.terminate()

                # Wait for it to stop
                try:
                    self._process.wait(timeout=10)
                    self._add_log_entry("Process terminated gracefully")
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't stop gracefully
                    self._add_log_entry("Process didn't stop gracefully, force killing")
                    self._process.kill()
                    self._process.wait()
                    self._add_log_entry("Process force killed")

            elif self._external_process:
                # This is an external process, we can't stop it directly
                self._add_log_entry("Cannot stop external docling-serve process - it was started outside the TUI")
                self._running = False
                self._external_process = False
                return False, "Cannot stop external docling-serve process. Please stop it manually."

            self._running = False
            self._process = None
            self._external_process = False

            self._add_log_entry("Docling serve stopped successfully")
            return True, "Docling serve stopped successfully"

        except Exception as e:
            self._add_log_entry(f"Error stopping docling serve: {e}")
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
            with self._log_lock:
                # If we have no logs but the service is running, it might have been started externally
                if not self._log_buffer:
                    return True, "No logs available yet..."

                # Return the most recent logs
                log_count = min(lines, len(self._log_buffer))
                logs = "\n".join(self._log_buffer[-log_count:])
                return True, logs
        else:
            return True, "Docling serve is not running."
    
    async def follow_logs(self) -> AsyncIterator[str]:
        """Follow logs from the docling-serve process in real-time."""
        # First yield status message and any existing logs
        status_msg = f"Docling serve is running on http://{self._host}:{self._port}"

        with self._log_lock:
            if self._log_buffer:
                yield "\n".join(self._log_buffer)
                last_log_index = len(self._log_buffer)
            else:
                yield "Waiting for logs..."
                last_log_index = 0

        # Then start monitoring for new logs
        while self.is_running():
            with self._log_lock:
                # Check if we have new logs
                if len(self._log_buffer) > last_log_index:
                    # Yield only the new logs
                    new_logs = self._log_buffer[last_log_index:]
                    yield "\n".join(new_logs)
                    last_log_index = len(self._log_buffer)

            # Wait a bit before checking again
            await asyncio.sleep(0.1)

        # Final check for any logs that came in during shutdown
        with self._log_lock:
            if len(self._log_buffer) > last_log_index:
                yield "\n".join(self._log_buffer[last_log_index:])
