"""Edit smoke test: builds a throw-away project 'resolve_mcp_test', exercises the editing tools,
then deletes it and reopens the project that was open before.

    uv run --project ~/resolve-mcp python scripts/edit_check.py
"""

import json
import os
import sys

import anyio
from mcp.client import Client

from resolve_mcp.server import mcp
from resolve_mcp.tools.timeline import _png

TEST = "resolve_mcp_test"
MEDIA = "/tmp/resolve_mcp_test"


def make_media() -> list[str]:
    os.makedirs(MEDIA, exist_ok=True)
    paths = []
    for name, rgb in (("red", (200, 40, 40)), ("green", (40, 180, 60)), ("blue", (40, 70, 200))):
        w, h = 320, 180
        data = bytes(rgb) * (w * h)
        p = f"{MEDIA}/{name}.png"
        with open(p, "wb") as f:
            f.write(_png(w, h, data))
        paths.append(p)
    return paths


async def main() -> int:
    results = []
    async with Client(mcp) as c:

        async def call(name, args=None, expect_ok=True):
            res = await c.call_tool(name, args or {})
            text = "".join(getattr(x, "text", "") for x in res.content)
            kinds = [x.type for x in res.content]
            ok = not res.is_error
            line = ("OK " if ok else "ERR") + f" {name}: " + (text[:160].replace("\n", " ") if text else str(kinds))
            results.append(line)
            print(line, flush=True)
            if not ok:
                return None
            try:
                return json.loads(text) if text else kinds
            except Exception:
                return text

        before = (await call("get_status"))["project"]
        if before == TEST:
            before = os.environ.get("REOPEN_PROJECT")
        projects = (await call("list_projects", {"folder": "/"}))["projects"]
        if TEST in projects:
            await call("close_project", {"save": False})
            await call("delete_project", {"name": TEST})
        await call("create_project", {"name": TEST})
        await call("set_project_settings", {"settings": {"timelineFrameRate": "25", "timelineResolutionWidth": "1920", "timelineResolutionHeight": "1080"}})
        paths = make_media()
        await call("create_bin", {"name": "Test/Plates"})
        imp = await call("import_media", {"items": paths, "bin": "Test/Plates"})
        tree = await call("get_media_pool_tree", {"include_clips": True})
        clips = (await call("list_clips", {"bin": "Test/Plates"}))["clips"]
        c0 = clips[0]["$ref"]
        await call("update_clip", {"clip": c0, "color": "Orange", "metadata": {"Scene": "12", "Take": "3", "Comments": "mcp test"}, "add_flags": ["Red"]})
        await call("get_clip", {"clip": "clip:Master/Test/Plates/red.png", "sections": ["metadata", "flags"]})
        await call("add_markers", {"target": c0, "markers": [{"frame": 5, "color": "Green", "name": "clip marker"}]})
        tl = await call("create_timeline", {"name": "MCP Test TL", "clips": [x["$ref"] for x in clips]})
        await call("list_timelines")
        await call("set_timeline_start_timecode", {"timecode": "01:00:00:00"})
        await call("add_track", {"track_type": "video", "name": "V2 overlay"})
        await call("append_to_timeline", {"clips": [{"clip": c0, "track": 2, "record_frame": 90000, "start": 0, "end": 49}]})
        await call("get_timeline", {})
        items = await call("list_track_items", {"track_type": "video", "detail": True})
        it0 = items[0]["$ref"]
        it1 = items[1]["$ref"]
        await call("update_item", {"item": it0, "properties": {"ZoomX": 1.2, "ZoomY": 1.2, "CompositeMode": "COMPOSITE_SCREEN"}, "color": "Teal", "add_flags": ["Blue"], "name": "renamed item"})
        await call("get_item", {"item": it0, "sections": ["basics", "properties", "markers"]})
        await call("add_transition", {"item": it1, "type": "Cross Dissolve", "duration": 12})
        await call("add_markers", {"markers": [{"frame": 10, "color": "Red", "name": "tl marker", "note": "hello", "custom_data": "abc"}, {"frame": 40, "color": "Blue", "name": "second"}]})
        await call("add_markers", {"target": it0, "markers": [{"frame": 3, "color": "Yellow", "name": "item marker"}]})
        await call("set_marker_custom_data", {"frame": 40, "custom_data": "xyz"})
        await call("get_markers", {"custom_data": "xyz"})
        await call("delete_markers", {"frame": 40})
        await call("get_markers")
        await call("playhead", {"timecode": "01:00:01:00"})
        await call("insert_effect_clip", {"kind": "title", "name": "Text"})
        await call("insert_effect_clip", {"kind": "fusion_title", "name": "Text+"})
        await call("set_timeline_mark_in_out", {"mark_in": 10, "mark_out": 60})
        await call("open_page", {"page": "color"})
        await call("get_node_graph", {"target": it0})
        await call("set_cdl", {"item": it0, "slope": [1.1, 1.0, 0.9], "offset": [0, 0, 0.01], "power": [1, 1, 1], "saturation": 0.9})
        await call("grade_versions", {"item": it0, "action": "add", "name": "mcp_v2"})
        await call("manage_color_group", {"action": "create", "name": "MCP Group"})
        await call("manage_color_group", {"action": "assign", "name": "MCP Group", "items": [it0, it1]})
        await call("list_color_groups", {"with_clips": True})
        await call("get_node_graph", {"target": "group:MCP Group:pre"})
        await call("playhead", {"timecode": "01:00:01:00"})
        await call("get_current_frame_thumbnail")
        await call("manage_stills", {"action": "grab"})
        await call("list_gallery", {"with_stills": True})
        await call("export_lut", {"item": it0, "path": f"{MEDIA}/grade.cube"})
        await call("open_page", {"page": "edit"})
        await call("fusion_comps", {"item": it0, "action": "add"})
        await call("get_fusion_comp", {"item": it0})
        await call("export_timeline", {"path": f"{MEDIA}/test.edl", "format": "edl"})
        await call("export_timeline", {"path": f"{MEDIA}/test.otio", "format": "otio"})
        await call("set_render_settings", {"format": "mov", "codec": "ProRes422", "settings": {"TargetDir": MEDIA, "CustomName": "mcp_render"}})
        job = await call("add_render_job")
        await call("list_render_jobs")
        await call("delete_render_jobs", {"all": True})
        dup = await call("duplicate_timeline", {"name": "MCP dup"})
        await call("call_api_batch", {"calls": [{"target": "timeline", "method": "GetTrackCount", "args": ["video"]}, {"target": "media_pool", "method": "GetRootFolder"}, {"target": {"$result": 1}, "method": "GetSubFolderList"}]})
        if dup:
            await call("delete_timelines", {"timelines": [dup["timeline"]["$ref"]]})
        await call("delete_items", {"items": [it1], "ripple": True})
        await call("save_project")
        # cleanup
        await call("close_project", {"save": False})
        await call("delete_project", {"name": TEST})
        if before and before != TEST:
            await call("open_project", {"name": before})
    errs = [r for r in results if r.startswith("ERR")]
    print(f"\n{len(results) - len(errs)} ok, {len(errs)} errors")
    return 1 if errs else 0


sys.exit(anyio.run(main))
