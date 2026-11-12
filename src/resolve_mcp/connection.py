"""Connection to a running DaVinci Resolve through its fusionscript library.

Every call into Resolve goes through one dedicated thread: the scripting bridge is not
thread-safe, and serialising calls keeps edits in a predictable order.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.machinery
import importlib.util
import os
import sys
from typing import Any, Callable

DEFAULT_LIBS = {
    "darwin": "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
    "win32": r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    "linux": "/opt/resolve/libs/Fusion/fusionscript.so",
}

HELP = (
    "Make sure DaVinci Resolve Studio is running and that "
    "Preferences > System > General > 'External scripting using' is set to 'Local'."
)


class ResolveConnectionError(RuntimeError):
    """Resolve is not reachable."""


class ResolveCallError(RuntimeError):
    """A Resolve call failed or returned an error value."""


_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="resolve")
_module: Any = None
_resolve: Any = None


def library_path() -> str:
    path = os.environ.get("RESOLVE_SCRIPT_LIB") or DEFAULT_LIBS.get(sys.platform, "")
    if not path or not os.path.exists(path):
        raise ResolveConnectionError(
            f"fusionscript library not found at {path!r}. Set RESOLVE_SCRIPT_LIB to its path."
        )
    return path


def _load_module() -> Any:
    global _module
    if _module is None:
        path = library_path()
        loader = importlib.machinery.ExtensionFileLoader("fusionscript", path)
        spec = importlib.util.spec_from_file_location("fusionscript", path, loader=loader)
        if spec is None:
            raise ResolveConnectionError(f"Cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        _module = module
    return _module


def _alive(resolve: Any) -> bool:
    try:
        return bool(resolve.GetVersionString())
    except Exception:
        return False


def get_resolve() -> Any:
    """The Resolve app object, (re)connecting when needed. Call only on the Resolve thread."""
    global _resolve
    if _resolve is not None and _alive(_resolve):
        return _resolve
    _resolve = None
    module = _load_module()
    host = os.environ.get("RESOLVE_HOST")
    resolve = module.scriptapp("Resolve", host) if host else module.scriptapp("Resolve")
    if resolve is None or not _alive(resolve):
        raise ResolveConnectionError("Cannot connect to DaVinci Resolve. " + HELP)
    _resolve = resolve
    return resolve


def run_sync(fn: Callable[[], Any]) -> Any:
    """Run `fn` on the Resolve thread and wait for it (for use outside the event loop)."""
    return _executor.submit(fn).result()


async def run(fn: Callable[[], Any]) -> Any:
    """Run `fn` on the Resolve thread from async code."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, fn)
