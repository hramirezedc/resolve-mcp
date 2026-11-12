"""The MCP server object and the decorator that runs tools on the Resolve thread."""

from __future__ import annotations

import functools
import json
import inspect
import traceback
from typing import Any, Callable

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .connection import ResolveConnectionError, get_resolve, run
from .refs import Ctx

INSTRUCTIONS = """\
Controls a running DaVinci Resolve Studio (21.x) through its scripting API. Start with
`get_status`.

Objects are addressed with reference strings, e.g. "timeline" (current), "timeline:<uid|name>",
"item:<uid>" (timeline item), "clip:<uid|Master/Bin/name>" (media pool item),
"folder:Master/Bin", "graph:item:<uid>", "color_group:<name>", "album:still:1",
"comp:<item uid>:1", "handle:<n>". Every object a tool returns is described as
{"$ref", "$type", "name"} and can be passed back as is. Frames are timeline frames;
track indexes are 1-based like in Resolve. Resolve constants are passed by name
(e.g. "EXPORT_EDL") or, inside call_api arguments, as {"$const": "EXPORT_EDL"}.

Coverage: dedicated tools exist for projects, media storage, media pool, clips, timelines,
tracks, items, markers, color (nodes, LUTs, CDL, versions, groups, gallery), Fusion comps,
Fairlight, AI features and rendering. For ANY other API method use `call_api` (or
`call_api_batch`); `list_api_methods`, `search_api`, `get_api_type` and `get_api_docs`
describe the full API. `execute_python` runs arbitrary Python as a last resort.
"""

ReadOnly = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
Edit = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
Destructive = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
_KINDS = {"read": ReadOnly, "edit": Edit, "destructive": Destructive}

mcp = MCPServer(name="resolve", title="DaVinci Resolve MCP", version=__version__, instructions=INSTRUCTIONS)


def _call(fn: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    ctx = Ctx(get_resolve())
    result = fn(ctx, **kwargs)
    if isinstance(result, Image):
        return result
    # One JSON text block per call (lists would otherwise be split into one block per element).
    return json.dumps(ctx.to_json(result), ensure_ascii=False, indent=1)


def tool(kind: str = "edit") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register `fn(ctx, ...)` as an MCP tool that runs on the Resolve thread.

    The first parameter (the Ctx) is hidden from the tool schema. Return values are converted
    to JSON, with Resolve objects described as references.
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())[1:]

        async def wrapper(**kwargs: Any) -> Any:
            try:
                return await run(functools.partial(_call, fn, kwargs))
            except ToolError:
                raise
            except ResolveConnectionError as exc:
                raise ToolError(str(exc)) from exc
            except (LookupError, ValueError, TypeError, RuntimeError) as exc:
                raise ToolError(f"{type(exc).__name__}: {exc}") from exc
            except Exception as exc:  # unexpected: include the tail of the traceback
                tail = "\n".join(traceback.format_exc().strip().splitlines()[-6:])
                raise ToolError(f"{type(exc).__name__}: {exc}\n{tail}") from exc

        wrapper.__name__ = fn.__name__
        wrapper.__qualname__ = fn.__qualname__
        wrapper.__doc__ = fn.__doc__
        wrapper.__module__ = fn.__module__
        wrapper.__signature__ = sig.replace(parameters=params, return_annotation=Any)  # type: ignore[attr-defined]
        wrapper.__annotations__ = {p.name: p.annotation for p in params} | {"return": Any}
        mcp.tool(annotations=_KINDS[kind])(wrapper)
        return fn

    return deco
