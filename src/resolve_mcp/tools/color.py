"""Color page: node graphs, LUTs, CDL, grade versions, color groups, gallery, AI color tools and Fusion comps."""

from typing import Any, Literal

from ..app import tool
from ..refs import check

LUT_TYPES = {"17": "EXPORT_LUT_17PTCUBE", "33": "EXPORT_LUT_33PTCUBE", "65": "EXPORT_LUT_65PTCUBE", "panasonic_vlut": "EXPORT_LUT_PANASONICVLUT"}
CACHE = {"auto": "CACHE_AUTO_ENABLED", "off": "CACHE_DISABLED", "on": "CACHE_ENABLED"}


# --------------------------------------------------------------------------- node graphs


@tool("read")
def get_node_graph(ctx, target: str, layer: int | None = None) -> Any:
    """Nodes of a node graph: index, label, LUT, cache mode and the tools used in each node.
    target: 'item:<uid>' (clip grade, optional layer), 'timeline' / 'timeline:<id>' or
    'group:<name>:pre' / 'group:<name>:post'."""
    graph = ctx.graph(target, layer)
    nodes = []
    for i in range(1, int(graph.GetNumNodes() or 0) + 1):
        nodes.append({"index": i, "label": graph.GetNodeLabel(i), "lut": graph.GetLUT(i), "cache_mode": graph.GetNodeCacheMode(i), "tools": graph.GetToolsInNode(i)})
    return {"node_count": len(nodes), "nodes": nodes}


@tool()
def set_node(ctx, target: str, node: int, lut: str | None = None, enabled: bool | None = None, cache: Literal["auto", "off", "on"] | None = None, layer: int | None = None) -> Any:
    """On one node (1-based) of a graph: set a LUT (absolute path or relative to the LUT folders;
    "" clears; run refresh_luts after adding LUT files), enable/disable it, or set its cache mode."""
    graph = ctx.graph(target, layer)
    report = {}
    if lut is not None:
        report["lut"] = bool(graph.SetLUT(node, lut))
    if enabled is not None:
        report["enabled"] = bool(graph.SetNodeEnabled(node, enabled))
    if cache is not None:
        report["cache"] = bool(graph.SetNodeCacheMode(node, ctx.const(CACHE[cache])))
    return report


@tool()
def apply_grade(ctx, target: str, drx_path: str | None = None, grade_mode: Literal[0, 1, 2] = 0, arri_cdl_lut: bool = False, reset: bool = False, layer: int | None = None) -> Any:
    """Apply a .drx grade file (grade_mode 0 = no keyframes, 1 = source timecode aligned, 2 = start
    frames aligned), apply the ARRI CDL+LUT from clip metadata, or reset all grades of a graph."""
    graph = ctx.graph(target, layer)
    if reset:
        check(graph.ResetAllGrades(), "reset grades")
    if arri_cdl_lut:
        check(graph.ApplyArriCdlLut(), "apply ARRI CDL/LUT")
    if drx_path:
        check(graph.ApplyGradeFromDRX(drx_path, grade_mode), f"apply {drx_path}")
    return {"ok": True}


@tool()
def set_cdl(ctx, item: str, slope: list[float], offset: list[float], power: list[float], saturation: float = 1.0, node: int = 1) -> Any:
    """Set an ASC CDL on a node of a timeline item's grade (slope / offset / power as [r, g, b])."""
    def fmt(v: list[float]) -> str:
        return " ".join(f"{x:g}" for x in v)

    cdl = {"NodeIndex": str(node), "Slope": fmt(slope), "Offset": fmt(offset), "Power": fmt(power), "Saturation": str(saturation)}
    check(ctx.item(item).SetCDL(cdl), "set CDL")
    return {"ok": True}


@tool()
def copy_grade(ctx, source: str, targets: list[str]) -> Any:
    """Copy the current grade of one timeline item onto other items."""
    check(ctx.item(source).CopyGrades(ctx.items(targets)), "copy grades")
    return {"ok": True}


@tool()
def export_lut(ctx, item: str, path: str, size: Literal["17", "33", "65", "panasonic_vlut"] = "33") -> Any:
    """Export a timeline item's grade as a LUT (.cube 17/33/65 points, or Panasonic VLUT)."""
    check(ctx.item(item).ExportLUT(ctx.const(LUT_TYPES[size]), path), "export LUT")
    return {"path": path}


@tool()
def refresh_luts(ctx) -> Any:
    """Rescan the LUT folders so newly added LUT files can be used."""
    check(ctx.project.RefreshLUTList(), "refresh LUT list")
    return {"ok": True}


@tool()
def reset_node_colors(ctx, item: str) -> Any:
    """Reset the node colors of a timeline item's graph."""
    check(ctx.item(item).ResetAllNodeColors(), "reset node colors")
    return {"ok": True}


# --------------------------------------------------------------------------- versions


@tool()
def grade_versions(ctx, item: str, action: Literal["list", "add", "load", "rename", "delete"], name: str | None = None, new_name: str | None = None, remote: bool = False) -> Any:
    """Color grade versions of a timeline item: list (local and remote), add, load, rename, delete.
    remote=true works on remote versions."""
    it = ctx.item(item)
    vtype = 1 if remote else 0
    if action == "add":
        check(it.AddVersion(name, vtype), "add version")
    elif action == "load":
        check(it.LoadVersionByName(name, vtype), "load version")
    elif action == "rename":
        check(it.RenameVersionByName(name, new_name, vtype), "rename version")
    elif action == "delete":
        check(it.DeleteVersionByName(name, vtype), "delete version")
    return {"current": it.GetCurrentVersion(), "local": it.GetVersionNameList(0), "remote": it.GetVersionNameList(1)}


# --------------------------------------------------------------------------- color groups


@tool("read")
def list_color_groups(ctx, with_clips: bool = False, timeline: str | int | None = None) -> Any:
    """Color groups of the project, optionally with their clips on a timeline."""
    out = []
    for g in ctx.project.GetColorGroupsList() or []:
        entry: dict[str, Any] = {"name": g.GetName(), "$ref": f"color_group:{g.GetName()}"}
        if with_clips:
            tl = ctx.timeline(timeline)
            entry["items"] = [{"$ref": f"item:{i.GetUniqueId()}", "name": i.GetName()} for i in g.GetClipsInTimeline(tl) or []]
        out.append(entry)
    return out


@tool()
def manage_color_group(ctx, action: Literal["create", "rename", "delete", "assign", "remove"], name: str | None = None, new_name: str | None = None, items: list[str] | None = None) -> Any:
    """Create / rename / delete a color group, assign timeline items to it, or remove items from their group."""
    project = ctx.project
    if action == "create":
        return {"group": check(project.AddColorGroup(name), "create color group")}
    if action == "rename":
        check(ctx.color_group(name).SetName(new_name), "rename color group")
    elif action == "delete":
        check(project.DeleteColorGroup(ctx.color_group(name)), "delete color group")
    elif action == "assign":
        group = ctx.color_group(name)
        return {i: bool(ctx.item(i).AssignToColorGroup(group)) for i in items or []}
    else:
        return {i: bool(ctx.item(i).RemoveFromColorGroup()) for i in items or []}
    return {"ok": True}


# --------------------------------------------------------------------------- AI color / effects


@tool()
def item_ai(ctx, item: str, action: Literal["magic_mask", "regenerate_magic_mask", "stabilize", "smart_reframe"], direction: Literal["F", "B", "BI"] = "BI") -> Any:
    """AI tools on a timeline item: Magic Mask (track forward F / backward B / both BI), regenerate
    Magic Mask, Stabilize, Smart Reframe. Requires Resolve Studio."""
    it = ctx.item(item)
    fn = {"magic_mask": lambda: it.CreateMagicMask(direction), "regenerate_magic_mask": it.RegenerateMagicMask, "stabilize": it.Stabilize, "smart_reframe": it.SmartReframe}[action]
    check(fn(), action)
    return {"ok": True}


# --------------------------------------------------------------------------- gallery


def _stills(ctx, album: Any) -> list[dict[str, Any]]:
    return [{"index": i, "label": album.GetLabel(s)} for i, s in enumerate(album.GetStills() or [], 1)]


@tool("read")
def list_gallery(ctx, with_stills: bool = False) -> Any:
    """Still and PowerGrade albums (refs 'album:still:<n>' / 'album:powergrade:<n>'), the current
    album, and optionally each album's stills (index and label)."""
    gallery = ctx.project.GetGallery()
    out: dict[str, Any] = {"current": gallery.GetAlbumName(gallery.GetCurrentStillAlbum())}
    for kind, albums in (("still", gallery.GetGalleryStillAlbums()), ("powergrade", gallery.GetGalleryPowerGradeAlbums())):
        entries = []
        for i, album in enumerate(albums or [], 1):
            e: dict[str, Any] = {"$ref": f"album:{kind}:{i}", "name": gallery.GetAlbumName(album)}
            if with_stills:
                e["stills"] = _stills(ctx, album)
            entries.append(e)
        out[f"{kind}_albums"] = entries
    return out


@tool()
def manage_album(ctx, action: Literal["create_still", "create_powergrade", "rename", "set_current"], album: str | None = None, name: str | None = None) -> Any:
    """Create a still or PowerGrade album, rename an album, or make it the current album."""
    gallery = ctx.project.GetGallery()
    if action == "create_still":
        a = check(gallery.CreateGalleryStillAlbum(), "create album")
    elif action == "create_powergrade":
        a = check(gallery.CreateGalleryPowerGradeAlbum(), "create PowerGrade album")
    else:
        a = ctx.album(album or "current")
    if action == "set_current":
        check(gallery.SetCurrentStillAlbum(a), "set current album")
    if name and action != "set_current":
        check(gallery.SetAlbumName(a, name), "rename album")
    return {"album": gallery.GetAlbumName(a)}


@tool()
def manage_stills(
    ctx,
    action: Literal["grab", "grab_all", "list", "import", "export", "delete", "label"],
    album: str = "album:current",
    indices: list[int] | None = None,
    paths: list[str] | None = None,
    folder: str | None = None,
    prefix: str = "still",
    format: Literal["dpx", "cin", "tif", "jpg", "png", "ppm", "bmp", "xpm", "drx"] = "dpx",
    label: str | None = None,
    source: Literal[1, 2] = 1,
) -> Any:
    """Gallery stills: grab the current frame (or all clips: source 1 = first frame, 2 = middle frame)
    into the current album, list, import image files, export (with .drx grades) to a folder,
    delete, or set the label of stills selected by 1-based `indices` (default all)."""
    if action in ("grab", "grab_all"):
        tl = ctx.timeline(None)
        result = tl.GrabStill() if action == "grab" else tl.GrabAllStills(source)
        check(result, action)
        return _stills(ctx, ctx.album("current"))
    alb = ctx.album(album)
    stills = alb.GetStills() or []
    chosen = [stills[i - 1] for i in indices] if indices else stills
    if action == "import":
        check(alb.ImportStills(paths or []), "import stills")
    elif action == "export":
        check(alb.ExportStills(chosen, folder, prefix, format), "export stills")
        return {"folder": folder, "count": len(chosen)}
    elif action == "delete":
        check(alb.DeleteStills(chosen), "delete stills")
    elif action == "label":
        for s in chosen:
            alb.SetLabel(s, label or "")
    return _stills(ctx, alb)


# --------------------------------------------------------------------------- Fusion


@tool()
def fusion_comps(ctx, item: str, action: Literal["list", "add", "import", "export", "load", "rename", "delete"], name: str | None = None, new_name: str | None = None, path: str | None = None, index: int = 1) -> Any:
    """Fusion compositions of a timeline item: list, add a new one, import a .comp, export one
    (by 1-based index) to a .comp, load (make active), rename or delete by name. The comp itself is
    reachable as 'comp:<item uid>:<index|name>' with call_api / execute_python (Fusion API)."""
    it = ctx.item(item)
    if action == "add":
        check(it.AddFusionComp(), "add Fusion comp")
    elif action == "import":
        check(it.ImportFusionComp(path), "import Fusion comp")
    elif action == "export":
        check(it.ExportFusionComp(path, index), "export Fusion comp")
        return {"path": path}
    elif action == "load":
        check(it.LoadFusionCompByName(name), "load Fusion comp")
    elif action == "rename":
        check(it.RenameFusionCompByName(name, new_name), "rename Fusion comp")
    elif action == "delete":
        check(it.DeleteFusionCompByName(name), "delete Fusion comp")
    return {"count": it.GetFusionCompCount(), "names": it.GetFusionCompNameList()}


@tool("read")
def get_fusion_comp(ctx, item: str, comp: str | int = 1) -> Any:
    """Tools of a Fusion composition (name, type, position in the flow, main inputs connected) and
    its render range. Edit it with execute_python via ctx.comp('<uid>:<n>')."""
    c = ctx.comp(f"{ctx.item(item).GetUniqueId()}:{comp}")
    tools = c.GetToolList(False) or {}
    flow = c.CurrentFrame.FlowView if getattr(c, "CurrentFrame", None) else None
    out = []
    for t in tools.values():
        attrs = t.GetAttrs() or {}
        entry: dict[str, Any] = {"name": attrs.get("TOOLS_Name"), "type": attrs.get("TOOLS_RegID"), "pass_through": attrs.get("TOOLB_PassThrough")}
        try:
            if flow:
                entry["pos"] = flow.GetPosTable(t)
        except Exception:
            pass
        try:
            inp = t.FindMainInput(1)
            src = inp.GetConnectedOutput() if inp else None
            entry["input"] = src.GetTool().GetAttrs().get("TOOLS_Name") if src else None
        except Exception:
            pass
        out.append(entry)
    attrs = c.GetAttrs() or {}
    return {"tools": out, "render_start": attrs.get("COMPN_RenderStart"), "render_end": attrs.get("COMPN_RenderEnd")}
