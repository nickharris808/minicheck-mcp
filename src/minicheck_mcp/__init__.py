"""minicheck-mcp — a model checker as an MCP server, so an AI agent can verify a state machine."""

from .server import TOOL_SCHEMAS, TOOLS, dispatch, main

__all__ = ["dispatch", "TOOLS", "TOOL_SCHEMAS", "main", "__version__"]
__version__ = "0.2.0"
