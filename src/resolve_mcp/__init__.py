"""Full-coverage MCP server for DaVinci Resolve Studio."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("resolve-mcp")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"


def main() -> None:
    from .cli import main as cli_main

    cli_main()
