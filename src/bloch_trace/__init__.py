"""Python SDK for Bloch Trace."""

from importlib.metadata import version as _version

from bloch_trace.client import TraceClient

__version__ = _version("bloch-trace")

__all__ = ["TraceClient", "__version__"]
