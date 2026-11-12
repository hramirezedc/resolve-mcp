"""Timelines, tracks, timeline items, markers, takes, transitions and editorial AI tools."""

import base64
import os
import tempfile
import struct
import zlib
from typing import Any, Literal

from mcp.server.mcpserver import Image

from ..app import tool
from ..refs import TRACK_TYPES, check
from ._types import ClipColor, FlagColor, MarkerColor, MarkType, TrackType

EXPORT_TYPES = {
    "aaf": "EXPORT_AAF", "drt": "EXPORT_DRT", "edl": "EXPORT_EDL", "fcp7xml": "EXPORT_FCP_7_XML",
    "fcpxml_1_8": "EXPORT_FCPXML_1_8", "fcpxml_1_9": "EXPORT_FCPXML_1_9", "fcpxml_1_10": "EXPORT_FCPXML_1_10",
    "hdr10_a": "EXPORT_HDR_10_PROFILE_A", "hdr10_b": "EXPORT_HDR_10_PROFILE_B", "csv": "EXPORT_TEXT_CSV",
    "tab": "EXPORT_TEXT_TAB", "dolby_vision_2_9": "EXPORT_DOLBY_VISION_VER_2_9",
    "dolby_vision_4_0": "EXPORT_DOLBY_VISION_VER_4_0", "dolby_vision_5_1": "EXPORT_DOLBY_VISION_VER_5_1",
    "otio": "EXPORT_OTIO", "ale": "EXPORT_ALE", "ale_cdl": "EXPORT_ALE_CDL",
}
EXPORT_SUBTYPES = {"none": "EXPORT_NONE", "aaf_new": "EXPORT_AAF_NEW", "aaf_existing": "EXPORT_AAF_EXISTING", "cdl": "EXPORT_CDL", "sdl": "EXPORT_SDL", "missing_clips": "EXPORT_MISSING_CLIPS"}


def _item_summary(item: Any, ttype: str | None = None, tindex: int | None = None, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "$ref": f"item:{item.GetUniqueId()}",
        "name": item.GetName(),
        "start": item.GetStart(),
        "end": item.GetEnd(),
        "duration": item.GetDuration(),
    }
    if ttype:
        out["track"] = [ttype, tindex]
    try:
        out["enabled"] = item.GetClipEnabled()
    except Exception:
        pass
    mpi = item.GetMediaPoolItem()
    if mpi:
        out["clip"] = f"clip:{mpi.GetUniqueId()}"
    if detail:
        out.update({
            "type": item.GetType(),
            "source_start": item.GetSourceStartFrame(),
            "source_end": item.GetSourceEndFrame(),
            "left_offset": item.GetLeftOffset(),
            "right_offset": item.GetRightOffset(),
            "color": item.GetClipColor(),
            "flags": item.GetFlagList(),
        })
    return out


def _tracks(tl: Any) -> list[dict[str, Any]]:
    out = []
    for ttype in TRACK_TYPES:
        for i in range(1, int(tl.GetTrackCount(ttype) or 0) + 1):
            out.append({
                "type": ttype, "index": i, "name": tl.GetTrackName(ttype, i), "subtype": tl.GetTrackSubType(ttype, i),
                "enabled": tl.GetIsTrackEnabled(ttype, i), "locked": tl.GetIsTrackLocked(ttype, i),
                "items": len(tl.GetItemListInTrack(ttype, i) or []),
            })
    return out


# --------------------------------------------------------------------------- timelines


@tool("read")
def list_timelines(ctx) -> Any:
    """Timelines of the current project (index, ref, name, frame range, start timecode) and the current one."""
    project = ctx.project
    cur = project.GetCurrentTimeline()
    cur_id = cur.GetUniqueId() if cur else None
    out = []
    for i, tl in enumerate(ctx.timelines(), 1):
        out.append({"index": i, "$ref": f"timeline:{tl.GetUniqueId()}", "name": tl.GetName(), "start": tl.GetStartFrame(), "end": tl.GetEndFrame(), "start_tc": tl.GetStartTimecode(), "current": tl.GetUniqueId() == cur_id})
    return out


@tool("read")
def get_timeline(ctx, timeline: str | int | None = None, include_settings: bool = False) -> Any:
    """A timeline's frame range, timecodes, playhead, tracks (name, subtype, enabled, locked, item
    count), marks, markers, output blanking and optionally its settings."""
    tl = ctx.timeline(timeline)
    out = {
        "timeline": tl, "start": tl.GetStartFrame(), "end": tl.GetEndFrame(), "start_tc": tl.GetStartTimecode(),
        "playhead_tc": tl.GetCurrentTimecode(), "tracks": _tracks(tl), "mark_in_out": tl.GetMarkInOut(),
        "markers": tl.GetMarkers(), "output_blanking": tl.GetOutputBlanking(), "media_pool_item": tl.GetMediaPoolItem(),
    }
    if include_settings:
        out["settings"] = tl.GetSettings()
    return out


@tool()
def set_current_timeline(ctx, timeline: str | int) -> Any:
    """Make a timeline the current (open) one."""
    tl = ctx.timeline(timeline)
    check(ctx.project.SetCurrentTimeline(tl), "set current timeline")
    return {"timeline": tl}


@tool()
def create_timeline(ctx, name: str, clips: list[Any] | None = None, bin: str | None = None) -> Any:
    """Create a timeline (empty, or from clips) in `bin` (default current bin). Each clip is a clip
    reference or {"clip", "start", "end", "record_frame"} with source frames for a sub-range."""
    mp = ctx.media_pool
    previous = mp.GetCurrentFolder()
    if bin is not None:
        mp.SetCurrentFolder(ctx.folder(bin))
    try:
        if clips:
            infos = []
            for c in clips:
                if isinstance(c, dict) and "clip" in c:
                    info = {"mediaPoolItem": ctx.clip(c["clip"])}
                    for src, dst in (("start", "startFrame"), ("end", "endFrame"), ("record_frame", "recordFrame")):
                        if c.get(src) is not None:
                            info[dst] = c[src]
                    infos.append(info)
                else:
                    infos.append({"mediaPoolItem": ctx.clip(c)})
            tl = mp.CreateTimelineFromClips(name, infos)
        else:
            tl = mp.CreateEmptyTimeline(name)
    finally:
        if bin is not None and previous:
            mp.SetCurrentFolder(previous)
    return {"timeline": check(tl, f"create timeline {name!r} (name already used?)")}


@tool()
def import_timeline(ctx, path: str, timeline_name: str | None = None, import_source_clips: bool = True, source_clips_path: str | None = None, source_clips_bins: list[str] | None = None, interlace_processing: bool | None = None) -> Any:
    """Import a timeline from AAF / EDL / XML / FCPXML / DRT / ADL / OTIO into the current project."""
    opts: dict[str, Any] = {"importSourceClips": import_source_clips}
    if timeline_name:
        opts["timelineName"] = timeline_name
    if source_clips_path:
        opts["sourceClipsPath"] = source_clips_path
    if source_clips_bins:
        opts["sourceClipsFolders"] = [ctx.folder(b) for b in source_clips_bins]
    if interlace_processing is not None:
        opts["interlaceProcessing"] = interlace_processing
    return {"timeline": check(ctx.media_pool.ImportTimelineFromFile(path, opts), f"import timeline {path}")}


@tool()
def import_into_timeline(ctx, path: str, timeline: str | int | None = None, options: dict[str, Any] | None = None) -> Any:
    """Import an AAF into an existing timeline (see get_api_type('AAFImportOptions'); sourceClipsFolders
    may be bin paths)."""
    tl = ctx.timeline(timeline)
    opts = dict(options or {})
    if "sourceClipsFolders" in opts:
        opts["sourceClipsFolders"] = [ctx.folder(b) for b in opts["sourceClipsFolders"]]
    check(tl.ImportIntoTimeline(path, opts) if opts else tl.ImportIntoTimeline(path), "import into timeline")
    return {"ok": True}


@tool()
def export_timeline(ctx, path: str, format: Literal[tuple(EXPORT_TYPES)], subtype: Literal[tuple(EXPORT_SUBTYPES)] = "none", timeline: str | int | None = None) -> Any:  # type: ignore[valid-type]
    """Export a timeline: AAF (subtype aaf_new / aaf_existing), EDL (subtype none / cdl / sdl /
    missing_clips), FCP 7 XML, FCPXML 1.8-1.10, DRT, OTIO, ALE, CSV / tab text, HDR10 or Dolby Vision metadata."""
    tl = ctx.timeline(timeline)
    check(tl.Export(path, ctx.const(EXPORT_TYPES[format]), ctx.const(EXPORT_SUBTYPES[subtype])), f"export {format}")
    return {"path": path}


@tool()
def duplicate_timeline(ctx, name: str | None = None, timeline: str | int | None = None) -> Any:
    """Duplicate a timeline (optionally naming the copy)."""
    tl = ctx.timeline(timeline)
    return {"timeline": check(tl.DuplicateTimeline(name) if name else tl.DuplicateTimeline(), "duplicate timeline")}


@tool()
def rename_timeline(ctx, name: str, timeline: str | int | None = None) -> Any:
    """Rename a timeline."""
    tl = ctx.timeline(timeline)
    check(tl.SetName(name), "rename timeline")
    return {"timeline": tl}


@tool("destructive")
def delete_timelines(ctx, timelines: list[str | int]) -> Any:
    """Delete timelines from the project."""
    check(ctx.media_pool.DeleteTimelines([ctx.timeline(t) for t in timelines]), "delete timelines")
    return {"ok": True}


@tool("read")
def get_timeline_settings(ctx, timeline: str | int | None = None, keys: list[str] | None = None) -> Any:
    """Timeline settings (all or `keys`); see get_api_type('TimelineSettings')."""
    settings = ctx.timeline(timeline).GetSettings() or {}
    return {k: settings.get(k) for k in keys} if keys else settings


@tool()
def set_timeline_settings(ctx, settings: dict[str, Any], timeline: str | int | None = None) -> Any:
    """Set timeline settings (e.g. useCustomSettings, timelineResolutionWidth, timelineFrameRate...).
    Keys failing as a group are retried one by one and reported."""
    tl = ctx.timeline(timeline)
    values = {k: (v if isinstance(v, str) else ("1" if v else "0") if isinstance(v, bool) else str(v)) for k, v in settings.items()}
    if tl.SetSettings(values):
        return {"ok": True}
    return {"ok": False, "per_key": {k: bool(tl.SetSettings({k: v})) for k, v in values.items()}}


@tool()
def set_timeline_start_timecode(ctx, timecode: str, timeline: str | int | None = None) -> Any:
    """Set a timeline's start timecode, e.g. '01:00:00:00'."""
    tl = ctx.timeline(timeline)
    check(tl.SetStartTimecode(timecode), "set start timecode")
    return {"start_tc": tl.GetStartTimecode(), "start": tl.GetStartFrame()}


@tool()
def playhead(ctx, timecode: str | None = None) -> Any:
    """Get the playhead timecode of the current timeline, or move it to `timecode`. Also returns the
    video item under the playhead."""
    tl = ctx.timeline(None)
    if timecode:
        check(tl.SetCurrentTimecode(timecode), f"move playhead to {timecode}")
    item = tl.GetCurrentVideoItem()
    return {"timecode": tl.GetCurrentTimecode(), "video_item": _item_summary(item) if item else None}


@tool()
def set_timeline_mark_in_out(ctx, mark_in: int | None = None, mark_out: int | None = None, mark_type: MarkType = "all", clear: bool = False, timeline: str | int | None = None) -> Any:
    """Set or clear a timeline's mark in/out (timeline frames)."""
    tl = ctx.timeline(timeline)
    check(tl.ClearMarkInOut(mark_type) if clear else tl.SetMarkInOut(mark_in, mark_out, mark_type), "marks")
    return tl.GetMarkInOut()


def _png(width: int, height: int, rgb: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


@tool("read")
def get_current_frame_thumbnail(ctx) -> Any:
    """Image (PNG) of the current frame so the agent can see it: the Color page thumbnail when
    available, otherwise the frame exported as a still."""
    data = ctx.timeline(None).GetCurrentClipThumbnailImage() or {}
    if data.get("data"):
        w, h = int(data["width"]), int(data["height"])
        return Image(data=_png(w, h, base64.b64decode(data["data"])[: w * h * 3]), format="png")
    fd, path = tempfile.mkstemp(suffix=".png", prefix="resolve_mcp_")
    os.close(fd)
    try:
        check(ctx.project.ExportCurrentFrameAsStill(path), "export current frame (is there a clip under the playhead?)")
        with open(path, "rb") as f:
            png = f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not png:
        raise RuntimeError("Resolve exported an empty frame.")
    return Image(data=png, format="png")


@tool()
def export_current_frame(ctx, path: str) -> Any:
    """Export the current frame (full resolution) as a still image file (.dpx, .tif, .png, .jpg, .exr...)."""
    check(ctx.project.ExportCurrentFrameAsStill(path), "export current frame")
    return {"path": path}


# --------------------------------------------------------------------------- tracks


@tool()
def add_track(ctx, track_type: TrackType, audio_subtype: Literal["mono", "stereo", "5.1", "5.1film", "7.1", "7.1film", "adaptive1", "adaptive2", "adaptive4", "adaptive6", "adaptive8", "adaptive10", "adaptive12", "adaptive16", "adaptive24", "adaptive36"] | None = None, name: str | None = None, timeline: str | int | None = None) -> Any:
    """Add a video, audio (with channel format) or subtitle track at the top, optionally naming it."""
    tl = ctx.timeline(timeline)
    check(tl.AddTrack(track_type, audio_subtype) if audio_subtype else tl.AddTrack(track_type), "add track")
    index = int(tl.GetTrackCount(track_type))
    if name:
        tl.SetTrackName(track_type, index, name)
    return {"type": track_type, "index": index}


@tool("destructive")
def delete_track(ctx, track_type: TrackType, index: int, timeline: str | int | None = None) -> Any:
    """Delete a track and everything on it."""
    check(ctx.timeline(timeline).DeleteTrack(track_type, index), "delete track")
    return {"ok": True}


@tool()
def update_track(ctx, track_type: TrackType, index: int, name: str | None = None, enabled: bool | None = None, locked: bool | None = None, voice_isolation: bool | None = None, voice_isolation_amount: int | None = None, timeline: str | int | None = None) -> Any:
    """Rename, enable/disable, lock/unlock a track; for audio tracks also set Voice Isolation."""
    tl = ctx.timeline(timeline)
    report = {}
    if name is not None:
        report["name"] = bool(tl.SetTrackName(track_type, index, name))
    if enabled is not None:
        report["enabled"] = bool(tl.SetTrackEnable(track_type, index, enabled))
    if locked is not None:
        report["locked"] = bool(tl.SetTrackLock(track_type, index, locked))
    if voice_isolation is not None or voice_isolation_amount is not None:
        state = dict(tl.GetVoiceIsolationState(index) or {})
        if voice_isolation is not None:
            state["isEnabled"] = voice_isolation
        if voice_isolation_amount is not None:
            state["amount"] = voice_isolation_amount
        report["voice_isolation"] = bool(tl.SetVoiceIsolationState(index, state))
    return report


# --------------------------------------------------------------------------- items


@tool("read")
def list_track_items(ctx, timeline: str | int | None = None, track_type: TrackType | None = None, track_index: int | None = None, detail: bool = False, limit: int = 1000) -> Any:
    """Items on a timeline (all tracks, one track type, or one track) with ref, name, record range,
    track, enabled, source clip. detail=true adds type, source range, offsets, color and flags."""
    tl = ctx.timeline(timeline)
    out = []
    for ttype, tindex, item in ctx.iter_items(tl, track_type):
        if track_index is not None and tindex != track_index:
            continue
        if len(out) >= limit:
            break
        out.append(_item_summary(item, ttype, tindex, detail))
    return out


@tool("read")
def get_selected_items(ctx, timeline: str | int | None = None) -> Any:
    """Timeline items currently selected in the UI."""
    return [_item_summary(i) for i in ctx.timeline(timeline).GetSelectedClips() or []]


@tool("read")
def get_item(ctx, item: str, sections: list[str] | None = None) -> Any:
    """Everything about a timeline item. sections (default all): basics, properties (transform,
    crop, composite, retime, stabilization...), speed, fades, markers, takes, versions, fusion,
    color, linked, audio, cache, output_blanking, stereo."""
    it = ctx.item(item)
    want = set(sections or ["basics", "properties", "speed", "fades", "markers", "takes", "versions", "fusion", "color", "linked", "audio", "cache", "output_blanking"])
    out: dict[str, Any] = {}
    if "basics" in want:
        out.update(_item_summary(it, detail=True))
        out["track"] = it.GetTrackTypeAndIndex()
    getters = {
        "properties": lambda: it.GetProperties(),
        "speed": lambda: it.GetSpeed(),
        "fades": lambda: it.GetFades(),
        "markers": lambda: it.GetMarkers(),
        "takes": lambda: {"count": it.GetTakesCount(), "selected": it.GetSelectedTakeIndex(), "takes": [it.GetTakeByIndex(i) for i in range(1, (it.GetTakesCount() or 0) + 1)]},
        "versions": lambda: {"current": it.GetCurrentVersion(), "local": it.GetVersionNameList(0), "remote": it.GetVersionNameList(1)},
        "fusion": lambda: it.GetFusionCompNameList(),
        "color": lambda: {"group": it.GetColorGroup(), "nodes": (it.GetNodeGraph() or None) and it.GetNodeGraph().GetNumNodes()},
        "linked": lambda: [_item_summary(i) for i in it.GetLinkedItems() or []],
        "audio": lambda: {"source_channel_mapping": it.GetSourceAudioChannelMapping(), "voice_isolation": it.GetVoiceIsolationState()},
        "cache": lambda: {"color_output": it.GetIsColorOutputCacheEnabled(), "fusion_output": it.GetIsFusionOutputCacheEnabled()},
        "output_blanking": lambda: {"blanking": it.GetOutputBlanking(), "use_timeline": it.GetUseTimelineForOutputBlanking()},
        "stereo": lambda: {"convergence": it.GetStereoConvergenceValues(), "left_window": it.GetStereoLeftFloatingWindowParams(), "right_window": it.GetStereoRightFloatingWindowParams()},
    }
    for key in want & set(getters):
        try:
            out[key] = getters[key]()
        except Exception as exc:
            out[key] = f"error: {exc}"
    return out


@tool()
def update_item(
    ctx,
    item: str,
    name: str | None = None,
    enabled: bool | None = None,
    color: ClipColor | Literal[""] | None = None,
    properties: dict[str, Any] | None = None,
    speed: dict[str, Any] | None = None,
    fade_in: int | None = None,
    fade_out: int | None = None,
    add_flags: list[FlagColor] | None = None,
    clear_flags: FlagColor | Literal["All"] | None = None,
    source_audio_channel_mapping: str | None = None,
    voice_isolation: dict[str, Any] | None = None,
    output_blanking: dict[str, int] | None = None,
    use_timeline_output_blanking: bool | None = None,
    color_output_cache: bool | None = None,
    fusion_output_cache: Literal["Auto", "On", "Off"] | None = None,
    burn_in_preset: str | None = None,
) -> Any:
    """Change a timeline item. properties: Inspector values validated all-or-nothing (Pan, Tilt,
    ZoomX/Y, RotationAngle, Crop*, Opacity, CompositeMode, RetimeProcess, Scaling...; constants by
    name e.g. "COMPOSITE_SCREEN"; see get_api_type('TimelineItemProperties')). speed: {Percentage,
    PitchCorrection, StretchKeyframesToFit, RippleTimeline}. voice_isolation: {isEnabled, amount}.
    output_blanking: {Top, Bottom, Left, Right}."""
    it = ctx.item(item)
    report: dict[str, Any] = {}
    if name is not None:
        report["name"] = bool(it.SetName(name))
    if enabled is not None:
        report["enabled"] = bool(it.SetClipEnabled(enabled))
    if color is not None:
        report["color"] = bool(it.ClearClipColor() if color == "" else it.SetClipColor(color))
    if properties:
        report["properties"] = bool(it.SetProperties(ctx.consts_in(properties)))
    if speed:
        report["speed"] = bool(it.SetSpeed(speed))
    if fade_in is not None or fade_out is not None:
        fades = dict(it.GetFades() or {})
        if fade_in is not None:
            fades["FadeIn"] = fade_in
        if fade_out is not None:
            fades["FadeOut"] = fade_out
        report["fades"] = bool(it.SetFades(fades))
    if clear_flags:
        report["clear_flags"] = bool(it.ClearFlags(clear_flags))
    for flag in add_flags or []:
        report[f"flag:{flag}"] = bool(it.AddFlag(flag))
    if source_audio_channel_mapping is not None:
        report["audio_mapping"] = bool(it.SetSourceAudioChannelMapping(source_audio_channel_mapping))
    if voice_isolation is not None:
        report["voice_isolation"] = bool(it.SetVoiceIsolationState(voice_isolation))
    if output_blanking is not None:
        report["output_blanking"] = bool(it.SetOutputBlanking(output_blanking))
    if use_timeline_output_blanking is not None:
        report["use_timeline_output_blanking"] = bool(it.SetUseTimelineForOutputBlanking(use_timeline_output_blanking))
    if color_output_cache is not None:
        report["color_output_cache"] = bool(it.SetColorOutputCache(color_output_cache))
    if fusion_output_cache is not None:
        report["fusion_output_cache"] = bool(it.SetFusionOutputCache(fusion_output_cache))
    if burn_in_preset is not None:
        report["burn_in_preset"] = bool(it.LoadBurnInPreset(burn_in_preset))
    return report


@tool()
def append_to_timeline(ctx, clips: list[Any], timeline: str | int | None = None) -> Any:
    """Append clips to a timeline (current by default). Each entry is a clip reference or
    {"clip", "start", "end" (source frames), "track" (1-based), "record_frame" (timeline frame),
    "media": "video"|"audio"} to place sub-ranges precisely."""
    if timeline is not None:
        check(ctx.project.SetCurrentTimeline(ctx.timeline(timeline)), "select timeline")
    infos = []
    for c in clips:
        if isinstance(c, dict) and "clip" in c:
            info: dict[str, Any] = {"mediaPoolItem": ctx.clip(c["clip"])}
            for src, dst in (("start", "startFrame"), ("end", "endFrame"), ("track", "trackIndex"), ("record_frame", "recordFrame")):
                if c.get(src) is not None:
                    info[dst] = c[src]
            if c.get("media"):
                info["mediaType"] = 1 if c["media"] == "video" else 2
            infos.append(info)
        else:
            infos.append({"mediaPoolItem": ctx.clip(c)})
    items = ctx.media_pool.AppendToTimeline(infos) or []
    return {"items": [_item_summary(i) for i in items]}


@tool("destructive")
def delete_items(ctx, items: list[str], ripple: bool = False) -> Any:
    """Delete timeline items (optionally ripple delete)."""
    its = ctx.items(items)
    tl = ctx.timeline(None)
    check(tl.DeleteClips(its, ripple), "delete items")
    return {"ok": True}


@tool()
def link_items(ctx, items: list[str], linked: bool = True) -> Any:
    """Link or unlink timeline items (e.g. a video clip and its audio)."""
    check(ctx.timeline(None).SetClipsLinked(ctx.items(items), linked), "link items")
    return {"ok": True}


@tool()
def create_compound_clip(ctx, items: list[str], name: str | None = None, start_timecode: str | None = None, fusion_clip: bool = False) -> Any:
    """Turn items of the current timeline into a compound clip (or into a Fusion clip with fusion_clip=true)."""
    tl = ctx.timeline(None)
    its = ctx.items(items)
    if fusion_clip:
        return {"item": check(tl.CreateFusionClip(its), "create Fusion clip")}
    opts = {k: v for k, v in {"name": name, "startTimecode": start_timecode}.items() if v}
    return {"item": check(tl.CreateCompoundClip(its, opts) if opts else tl.CreateCompoundClip(its), "create compound clip")}


@tool()
def insert_effect_clip(ctx, kind: Literal["generator", "fusion_generator", "ofx_generator", "title", "fusion_title", "fusion_composition"], name: str | None = None) -> Any:
    """Insert a generator, Fusion generator, OFX generator, title, Fusion title or an empty Fusion
    composition into the current timeline at the playhead (e.g. kind='title' name='Text' or 'Scroll';
    kind='fusion_title' name='Text+')."""
    tl = ctx.timeline(None)
    fn = {
        "generator": lambda: tl.InsertGeneratorIntoTimeline(name),
        "fusion_generator": lambda: tl.InsertFusionGeneratorIntoTimeline(name),
        "ofx_generator": lambda: tl.InsertOFXGeneratorIntoTimeline(name),
        "title": lambda: tl.InsertTitleIntoTimeline(name),
        "fusion_title": lambda: tl.InsertFusionTitleIntoTimeline(name),
        "fusion_composition": lambda: tl.InsertFusionCompositionIntoTimeline(),
    }[kind]
    return {"item": check(fn(), f"insert {kind} {name or ''}")}


@tool()
def add_transition(
    ctx,
    item: str,
    type: str = "Cross Dissolve",
    category: Literal["simple", "fusion", "ofx", "audio"] = "simple",
    position: Literal["start", "end"] = "start",
    alignment: Literal["left", "center", "right"] = "center",
    duration: int | None = None,
) -> Any:
    """Add a transition at the start or end edge of a timeline item (e.g. type 'Cross Dissolve',
    'Dip To Color Dissolve', 'Smooth Cut'; category simple / fusion / ofx / audio). The item needs
    media handles on that edge. Returns the transition item."""
    opts: dict[str, Any] = {"type": type, "category": category, "position": position, "alignment": alignment}
    if duration is not None:
        opts["duration"] = duration
    return {"transition": check(ctx.item(item).AddTransition(opts), "add transition (check type/category and that the edge has handles)")}


@tool()
def manage_takes(ctx, item: str, action: Literal["list", "add", "select", "delete", "finalize"], clip: str | None = None, index: int | None = None, start: int | None = None, end: int | None = None) -> Any:
    """Take selector on a timeline item: list takes, add a clip as a take (optional source range),
    select / delete a take by 1-based index, or finalize the selected take."""
    it = ctx.item(item)
    if action == "add":
        c = ctx.clip(clip)
        check(it.AddTake(c, start, end) if start is not None else it.AddTake(c), "add take")
    elif action == "select":
        check(it.SelectTakeByIndex(index), "select take")
    elif action == "delete":
        check(it.DeleteTakeByIndex(index), "delete take")
    elif action == "finalize":
        check(it.FinalizeTake(), "finalize take")
        return {"ok": True}
    n = it.GetTakesCount() or 0
    return {"selected": it.GetSelectedTakeIndex(), "takes": [it.GetTakeByIndex(i) for i in range(1, n + 1)]}


@tool()
def timeline_ai(
    ctx,
    action: Literal["detect_scene_cuts", "create_subtitles", "normalize_audio", "auto_align", "convert_to_stereo", "dolby_vision_analysis", "smart_switch", "flatten_multicam"],
    items: list[str] | None = None,
    options: dict[str, Any] | None = None,
    timeline: str | int | None = None,
) -> Any:
    """Timeline-level tools. detect_scene_cuts; create_subtitles (options: language AUTO_CAPTION_*,
    captionPreset, charsPerLine, lineBreak, gap); normalize_audio (items; options: normalizationMode,
    targetLevel, targetLoudness, setLevelMode — see list_api_methods('Timeline') for modes);
    auto_align (items; options SyncUsing, UseTrack); convert_to_stereo; dolby_vision_analysis (items);
    smart_switch (one multicam item; SmartSwitchSettings); flatten_multicam (one item;
    options {grade: FLATTEN_MULTICAM_*}). Constant names in options are converted."""
    tl = ctx.timeline(timeline)
    opts = ctx.consts_in(options or {})
    its = ctx.items(items or [], timeline)
    if action == "detect_scene_cuts":
        ok = tl.DetectSceneCuts()
    elif action == "create_subtitles":
        ok = tl.CreateSubtitlesFromAudio(opts) if opts else tl.CreateSubtitlesFromAudio()
    elif action == "normalize_audio":
        ok = tl.NormalizeAudioLevel(its, opts) if opts else tl.NormalizeAudioLevel(its)
        if not ok:
            return {"ok": False, "modes": tl.GetNormalizeAudioModes()}
    elif action == "auto_align":
        ok = tl.AutoAlignClips(its, opts) if opts else tl.AutoAlignClips(its)
    elif action == "convert_to_stereo":
        ok = tl.ConvertTimelineToStereo()
    elif action == "dolby_vision_analysis":
        ok = tl.AnalyzeDolbyVision(its, opts.get("analysisType", ctx.resolve.DLB_BLEND_SHOTS)) if opts else tl.AnalyzeDolbyVision(its)
    elif action == "smart_switch":
        ok = its[0].PerformMulticamSmartSwitch(opts)
    else:
        ok = its[0].FlattenMulticam(opts.get("grade", ctx.resolve.FLATTEN_MULTICAM_COPY_GRADE))
    check(ok, action)
    return {"ok": True}


@tool()
def set_output_blanking(ctx, top: int = 0, bottom: int = 0, left: int = 0, right: int = 0, timeline: str | int | None = None) -> Any:
    """Timeline output blanking in pixels (letterbox / pillarbox)."""
    tl = ctx.timeline(timeline)
    check(tl.SetOutputBlanking({"Top": top, "Bottom": bottom, "Left": left, "Right": right}), "set output blanking")
    return tl.GetOutputBlanking()


# --------------------------------------------------------------------------- markers


def _marker_target(ctx, target: str) -> Any:
    if target in ("timeline", "") or target.startswith("timeline:"):
        return ctx.timeline(target if target.startswith("timeline:") else None)
    if target.startswith("item:"):
        return ctx.item(target)
    if target.startswith("clip:"):
        return ctx.clip(target)
    raise ValueError("Marker targets are 'timeline', 'timeline:<id>', 'item:<uid>' or 'clip:<uid|path>'.")


@tool("read")
def get_markers(ctx, target: str = "timeline", custom_data: str | None = None) -> Any:
    """Markers of a timeline, timeline item or media pool clip, keyed by frame (or the one marker
    with `custom_data`). Timeline markers are relative to the timeline start."""
    obj = _marker_target(ctx, target)
    return obj.GetMarkerByCustomData(custom_data) if custom_data else obj.GetMarkers()


@tool()
def add_markers(ctx, markers: list[dict[str, Any]], target: str = "timeline") -> Any:
    """Add markers to a timeline, item or clip. Each marker: {"frame", "color" (Blue, Cyan, Green,
    Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream),
    "name", "note", "duration" (default 1), "custom_data"}."""
    obj = _marker_target(ctx, target)
    report = []
    for m in markers:
        args = [int(m["frame"]), m.get("color", "Blue"), m.get("name", ""), m.get("note", ""), int(m.get("duration", 1))]
        if m.get("custom_data") is not None:
            args.append(m["custom_data"])
        report.append({"frame": m["frame"], "ok": bool(obj.AddMarker(*args))})
    return report


@tool("destructive")
def delete_markers(ctx, target: str = "timeline", frame: int | None = None, color: MarkerColor | Literal["All"] | None = None, custom_data: str | None = None) -> Any:
    """Delete markers at a frame, by color ('All' deletes every marker) or by custom data."""
    obj = _marker_target(ctx, target)
    if frame is not None:
        ok = obj.DeleteMarkerAtFrame(frame)
    elif color:
        ok = obj.DeleteMarkersByColor(color)
    elif custom_data is not None:
        ok = obj.DeleteMarkerByCustomData(custom_data)
    else:
        raise ValueError("Give frame, color or custom_data.")
    check(ok, "delete markers")
    return {"ok": True}


@tool()
def set_marker_custom_data(ctx, frame: int, custom_data: str, target: str = "timeline") -> Any:
    """Set the custom data string of the marker at `frame`."""
    obj = _marker_target(ctx, target)
    check(obj.UpdateMarkerCustomData(frame, custom_data), "update marker custom data")
    return {"custom_data": obj.GetMarkerCustomData(frame)}
