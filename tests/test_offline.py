"""Tests that run without Resolve."""

from mcp.client import Client

from resolve_mcp import api_index
from resolve_mcp.server import mcp


async def test_tools_registered_with_clean_schemas() -> None:
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    names = {t.name for t in tools}
    assert len(tools) > 90
    for required in ("get_status", "call_api", "call_api_batch", "list_track_items", "get_node_graph", "start_render", "execute_python"):
        assert required in names
    for t in tools:
        props = t.input_schema.get("properties", {})
        assert "ctx" not in props, t.name
        assert t.description, t.name


async def test_annotations() -> None:
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in ("delete_items", "delete_project", "call_api", "execute_python", "delete_timelines"):
        assert tools[name].annotations.destructive_hint is True
    for name in ("get_status", "list_clips", "get_item", "search_api"):
        assert tools[name].annotations.read_only_hint is True


def test_api_index_covers_every_class() -> None:
    assert "TimelineItem" in api_index.class_names()
    assert len(api_index.methods("TimelineItem")) > 80
    assert "EXPORT_EDL" in api_index.constants("EXPORT_")
    assert "Studio and AI" in api_index.docs("TOC")
    assert api_index.search("MagicMask")


def test_typed_tools_only_call_existing_api_methods() -> None:
    """Every Resolve method name used in the tool modules exists in the 21.1 stubs."""
    import ast
    import pathlib
    import re

    known = {m for c in api_index.class_names() for m in api_index.methods(c)}
    fusion_api = {"GetToolList", "GetAttrs", "GetPosTable", "FindMainInput", "GetConnectedOutput", "GetTool", "SetSetting"}
    root = pathlib.Path(api_index.__file__).parent / "tools"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and re.fullmatch(r"[A-Z][A-Za-z0-9]+", node.attr) and node.attr.startswith(("Get", "Set", "Add", "Delete", "Create", "Import", "Export", "Load", "Save", "Update", "Insert", "Clear", "Is", "Open", "Start", "Stop", "Rename", "Apply", "Reset", "Refresh", "Link", "Unlink", "Relink", "Replace", "Move", "Append", "Transcribe", "Perform", "Analyze", "Detect", "Convert", "Grab", "Copy", "Select", "Finalize", "Regenerate", "Stabilize", "Smart", "Flatten", "Monitor", "Remove", "Auto", "Normalize", "Duplicate", "Archive", "Restore", "Close", "Goto", "Quit", "Validate", "Encrypt", "Disable", "Reveal", "Render", "Generate", "Assign")):
                assert node.attr in known or node.attr in fusion_api, f"{path.name}: {node.attr} not in API"
