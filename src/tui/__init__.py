"""OpenRAG Terminal User Interface package."""

from importlib.metadata import version

try:
    __version__ = version("openrag")
except Exception:
    __version__ = "unknown"
