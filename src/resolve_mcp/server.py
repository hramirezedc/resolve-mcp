"""Importing this module builds the server with every tool registered."""

from .app import mcp  # noqa: F401
from . import tools  # noqa: F401  (registers the tools)
