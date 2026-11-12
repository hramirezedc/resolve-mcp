"""Read-only smoke test against a running Resolve: calls every read tool that needs no arguments
or can be fed from earlier results, and reports failures. Usage:

    uv run --project ~/resolve-mcp python scripts/live_check.py
"""

import json
import sys

import anyio
from mcp.client import Client

from resolve_mcp.server import mcp


async def main() -> int:
    failures = []
    report = {}
    async with Client(mcp) as c:

        async def call(name, args=None):
            res = await c.call_tool(name, args or {})
            text = "".join(getattr(x, "text", "") for x in res.content)
            if res.is_error:
                failures.append(f"{name}({args}): {text[:300]}")
                return None
            try:
                return json.loads(text) if text else res.structured_content
            except Exception:
                return text

        status = await call("get_status")
        report["status"] = status
        for kind in ("layout", "render", "burn_in", "keyboard", "fairlight", "user_preferences", "project_settings", "quick_export"):
            await call("list_presets", {"kind": kind})
        await call("list_projects", {"with_attributes": True})
        await call("list_databases")
        ps = await call("get_project_settings", {"keys": ["timelineFrameRate", "timelineResolutionWidth", "colorScienceMode"]})
        report["project_settings"] = ps
        vols = await call("list_volumes")
        if vols:
            await call("browse_storage", {"path": vols[0]})
        tree = await call("get_media_pool_tree", {"depth": 2})
        clips = await call("list_clips", {"limit": 5})
        report["clips"] = clips and clips.get("count")
        if clips and clips["clips"]:
            await call("get_clip", {"clip": clips["clips"][0]["$ref"]})
            await call("get_markers", {"target": clips["clips"][0]["$ref"]})
        await call("get_selected_clips")
        tls = await call("list_timelines")
        report["timelines"] = len(tls or [])
        if tls:
            await call("get_timeline", {"include_settings": True})
            await call("get_timeline_settings", {"keys": ["timelineFrameRate"]})
            await call("playhead")
            await call("get_markers")
            items = await call("list_track_items", {"detail": True, "limit": 5})
            report["items"] = len(items or [])
            if items:
                await call("get_item", {"item": items[0]["$ref"]})
                await call("get_node_graph", {"target": items[0]["$ref"]})
                await call("call_api", {"target": items[0]["$ref"], "method": "GetName"})
            await call("get_selected_items")
            await call("list_color_groups", {"with_clips": True})
        await call("list_gallery", {"with_stills": True})
        await call("get_render_options", {"format": "mov"})
        await call("list_render_jobs")
        await call("render_status")
        await call("list_api_methods", {"class_name": "Graph"})
        await call("search_api", {"query": "subtitle"})
        await call("get_api_type", {"name": "RenderSettings"})
        await call("get_api_docs", {"section": "Audio Mapping"})
        await call("list_constants", {"prefix": "EXPORT_"})
        await call("call_api", {"target": "project", "method": "GetName"})
        await call("call_api_batch", {"calls": [{"target": "project", "method": "GetMediaPool"}, {"target": {"$result": 0}, "method": "GetRootFolder"}, {"target": {"$result": 1}, "method": "GetName"}]})
        await call("execute_python", {"code": "result = {'name': project.GetName(), 'root': media_pool.GetRootFolder()}"})
    print(json.dumps(report, indent=1, default=str)[:3000])
    print("FAILURES:" if failures else "ALL OK", *failures, sep="\n")
    return 1 if failures else 0


sys.exit(anyio.run(main))
