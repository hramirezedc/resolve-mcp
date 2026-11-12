"""Media storage, media pool bins and clips (media pool items)."""

from typing import Any, Literal

from ..app import tool
from ..refs import check
from ._types import ClipColor, FlagColor, MarkType

BASIC_PROPS = ("Type", "File Path", "Duration", "FPS", "Resolution", "Start TC", "End TC", "Clip Color", "Video Codec", "Audio Ch")


def _clip_summary(clip: Any, bin_path: str | None = None, props: tuple[str, ...] | list[str] | None = BASIC_PROPS) -> dict[str, Any]:
    out: dict[str, Any] = {"$ref": f"clip:{clip.GetUniqueId()}", "name": clip.GetName()}
    if bin_path is not None:
        out["bin"] = bin_path
    if props:
        all_props = clip.GetClipProperty() or {}
        out.update({k: all_props.get(k) for k in props if k in all_props})
    return out


# --------------------------------------------------------------------------- media storage


@tool("read")
def list_volumes(ctx) -> Any:
    """Volumes mounted in Resolve's Media Storage."""
    return ctx.resolve.GetMediaStorage().GetMountedVolumeList()


@tool("read")
def browse_storage(ctx, path: str) -> Any:
    """Sub-folders and media files of an absolute path as Media Storage sees it (image sequences
    are consolidated into single entries)."""
    ms = ctx.resolve.GetMediaStorage()
    return {"folders": ms.GetSubFolderList(path), "files": ms.GetFileList(path)}


@tool()
def reveal_in_storage(ctx, path: str) -> Any:
    """Show a file or folder in the Media page's storage browser."""
    check(ctx.resolve.GetMediaStorage().RevealInStorage(path), f"reveal {path}")
    return {"ok": True}


@tool()
def import_media(ctx, items: list[Any], bin: str | None = None, via_media_storage: bool = False) -> Any:
    """Import files or folders into the media pool (into `bin`, default the current bin).
    Each item is a path, or {"path", "start", "end"} to import a frame range of an image sequence.
    via_media_storage=true uses Media Storage's AddItemListToMediaPool (honours its sequence
    detection and start/end frames)."""
    mp = ctx.media_pool
    previous = mp.GetCurrentFolder()
    if bin is not None:
        check(mp.SetCurrentFolder(ctx.folder(bin)), f"select bin {bin}")
    try:
        clips: list[Any] = []
        plain: list[str] = []
        ranged: list[dict[str, Any]] = []
        for it in items:
            path, start, end = (it, None, None) if isinstance(it, str) else (it["path"], it.get("start"), it.get("end"))
            if via_media_storage:
                info: dict[str, Any] = {"media": path}
                if start is not None:
                    info["startFrame"] = int(start)
                if end is not None:
                    info["endFrame"] = int(end)
                ranged.append(info)
            elif start is None and end is None:
                plain.append(path)
            else:
                ranged.append({"FilePath": path, "StartIndex": int(start if start is not None else 0), "EndIndex": int(end if end is not None else start)})
        if via_media_storage:
            clips += ctx.resolve.GetMediaStorage().AddItemListToMediaPool(ranged) or []
        else:
            # Plain paths use the list form: the {"FilePath"} dict form needs StartIndex/EndIndex in 21.1.
            if plain:
                clips += mp.ImportMedia(plain) or []
            if ranged:
                clips += mp.ImportMedia(ranged) or []
    finally:
        if bin is not None and previous:
            mp.SetCurrentFolder(previous)
    clips = clips or []
    return {"imported": [_clip_summary(c, props=("Type", "Duration", "FPS", "Resolution")) for c in clips], "count": len(clips)}


@tool()
def clone_media(
    ctx,
    action: Literal["start", "stop", "status", "settings"],
    source_dir: str | None = None,
    target_dirs: list[str] | None = None,
    preserve_folder_name: bool | None = None,
    checksum: str | None = None,
) -> Any:
    """Clone tool (camera-card offload with verification). 'settings' sets preserve_folder_name and
    checksum (CLONE_CHECKSUM_TYPE_NONE/FILESIZE/CRC32/MD5/SHA256/SHA512/XXH_64); 'start' copies
    source_dir to target_dirs; 'status' reports progress; 'stop' cancels."""
    ms = ctx.resolve.GetMediaStorage()
    if action == "settings":
        opts: dict[str, Any] = {}
        if preserve_folder_name is not None:
            opts["PreserveFolderName"] = preserve_folder_name
        if checksum:
            opts["ChecksumType"] = ctx.const(checksum)
        check(ms.SetCloneToolSettings(opts), "set clone settings")
        return {"ok": True}
    if action == "start":
        check(ms.StartCloneMedia(source_dir, target_dirs or []), "start clone")
        return ms.GetCloneStatus()
    if action == "stop":
        check(ms.StopCloneMedia(), "stop clone")
    return ms.GetCloneStatus()


# --------------------------------------------------------------------------- bins


def _tree(ctx, folder: Any, path: str, depth: int, include_clips: bool) -> dict[str, Any]:
    node: dict[str, Any] = {"$ref": f"folder:{folder.GetUniqueId()}", "name": folder.GetName(), "path": path, "clip_count": len(folder.GetClipList() or [])}
    if include_clips:
        node["clips"] = [{"$ref": f"clip:{c.GetUniqueId()}", "name": c.GetName()} for c in folder.GetClipList() or []]
    subs = folder.GetSubFolderList() or []
    if depth > 0:
        node["bins"] = [_tree(ctx, f, f"{path}/{f.GetName()}", depth - 1, include_clips) for f in subs]
    elif subs:
        node["bins_not_shown"] = len(subs)
    return node


@tool("read")
def get_media_pool_tree(ctx, bin: str | None = None, depth: int = 8, include_clips: bool = False) -> Any:
    """Bin hierarchy of the media pool (from the root or `bin`), with clip counts and optionally the
    clips. Also returns the current bin."""
    folder = ctx.folder(bin)
    mp = ctx.media_pool
    return {"current_bin": ctx.folder_path(mp.GetCurrentFolder()), "tree": _tree(ctx, folder, ctx.folder_path(folder), depth, include_clips)}


@tool()
def create_bin(ctx, name: str, parent: str | None = None) -> Any:
    """Create a bin (sub-folder) under `parent` (default: root). Use "A/B/C" in name to create nested bins."""
    mp = ctx.media_pool
    previous = mp.GetCurrentFolder()
    folder = ctx.folder(parent)
    for part in [p for p in name.split("/") if p]:
        existing = next((f for f in folder.GetSubFolderList() or [] if f.GetName() == part), None)
        folder = existing or check(mp.AddSubFolder(folder, part), f"create bin {part!r}")
    if previous:
        mp.SetCurrentFolder(previous)  # AddSubFolder selects the new bin
    return {"bin": folder, "path": ctx.folder_path(folder)}


@tool()
def set_current_bin(ctx, bin: str) -> Any:
    """Make a bin the current media pool folder (where imports and new timelines land)."""
    check(ctx.media_pool.SetCurrentFolder(ctx.folder(bin)), f"select bin {bin}")
    return {"current_bin": ctx.folder_path(ctx.media_pool.GetCurrentFolder())}


@tool("destructive")
def delete_bins(ctx, bins: list[str]) -> Any:
    """Delete bins and everything they contain."""
    check(ctx.media_pool.DeleteFolders([ctx.folder(b) for b in bins]), "delete bins")
    return {"ok": True}


@tool()
def move_bins(ctx, bins: list[str], target: str) -> Any:
    """Move bins into another bin."""
    check(ctx.media_pool.MoveFolders([ctx.folder(b) for b in bins], ctx.folder(target)), "move bins")
    return {"ok": True}


@tool()
def refresh_bins(ctx) -> Any:
    """Refresh the media pool folders (picks up changes from collaborators) and report stale bins."""
    mp = ctx.media_pool
    mp.RefreshFolders()
    return {"stale_bins": [p for p, f in ctx.walk_folders() if f.GetIsFolderStale()]}


@tool()
def import_bin(ctx, path: str, source_clips_path: str | None = None) -> Any:
    """Import a .drb bin file into the current bin (optionally relinking to source_clips_path)."""
    mp = ctx.media_pool
    check(mp.ImportFolderFromFile(path, source_clips_path) if source_clips_path else mp.ImportFolderFromFile(path), f"import bin {path}")
    return {"ok": True}


@tool()
def export_bin(ctx, bin: str, path: str) -> Any:
    """Export a bin to a .drb file."""
    check(ctx.folder(bin).Export(path), f"export bin to {path}")
    return {"path": path}


# --------------------------------------------------------------------------- clips


@tool("read")
def list_clips(
    ctx,
    bin: str | None = None,
    recursive: bool = True,
    name_contains: str | None = None,
    properties: list[str] | None = None,
    limit: int = 500,
) -> Any:
    """Clips in the media pool (or in `bin`), with their bin path and a few properties
    (default: Type, File Path, Duration, FPS, Resolution, Start/End TC, Clip Color, codec, audio
    channels). Pass `properties` for others (see get_api_type('ClipProperties')), [] for none."""
    folder = ctx.folder(bin) if bin is not None else None
    props = BASIC_PROPS if properties is None else properties
    out = []
    total = 0
    for path, clip in ctx.iter_clips(folder, recursive):
        if name_contains and name_contains.lower() not in clip.GetName().lower():
            continue
        total += 1
        if len(out) < limit:
            out.append(_clip_summary(clip, path, props))
    return {"count": total, "clips": out, "truncated": total > len(out)}


@tool("read")
def get_clip(ctx, clip: str, sections: list[str] | None = None) -> Any:
    """Everything about a media pool clip. sections (default all): properties, metadata,
    third_party_metadata, markers, flags, mark_in_out, audio_mapping, media_id, mattes, timeline."""
    c = ctx.clip(clip)
    want = set(sections or ["properties", "metadata", "third_party_metadata", "markers", "flags", "mark_in_out", "audio_mapping", "media_id", "mattes", "timeline"])
    out: dict[str, Any] = {"clip": c, "color": c.GetClipColor()}
    getters = {
        "properties": lambda: c.GetClipProperty(),
        "metadata": lambda: c.GetMetadata(),
        "third_party_metadata": lambda: c.GetThirdPartyMetadata(),
        "markers": lambda: c.GetMarkers(),
        "flags": lambda: c.GetFlagList(),
        "mark_in_out": lambda: c.GetMarkInOut(),
        "audio_mapping": lambda: c.GetAudioMapping(),
        "media_id": lambda: c.GetMediaId(),
        "mattes": lambda: ctx.media_pool.GetClipMatteList(c),
        "timeline": lambda: c.GetTimeline(),
    }
    for key in want & set(getters):
        try:
            out[key] = getters[key]()
        except Exception as exc:
            out[key] = f"error: {exc}"
    return out


@tool()
def update_clip(
    ctx,
    clip: str,
    name: str | None = None,
    color: ClipColor | Literal[""] | None = None,
    properties: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    third_party_metadata: dict[str, Any] | None = None,
    add_flags: list[FlagColor] | None = None,
    clear_flags: FlagColor | Literal["All"] | None = None,
    audio_mapping: str | None = None,
) -> Any:
    """Change a media pool clip: rename, clip color ("" clears), clip properties (e.g. "Clip Name",
    "Input Color Space", "Data Level", "Reel Name"...), metadata (e.g. Scene, Take, Comments),
    third-party metadata, flags and audio mapping (JSON string, see get_api_docs('Audio Mapping'))."""
    c = ctx.clip(clip)
    report: dict[str, Any] = {}
    if name is not None:
        report["name"] = bool(c.SetName(name))
    if color is not None:
        report["color"] = bool(c.ClearClipColor() if color == "" else c.SetClipColor(color))
    for key, value in (properties or {}).items():
        report[f"property:{key}"] = bool(c.SetClipProperty(key, value if isinstance(value, str) else str(value)))
    if metadata:
        report["metadata"] = bool(c.SetMetadata({k: str(v) for k, v in metadata.items()}))
    if third_party_metadata:
        report["third_party_metadata"] = bool(c.SetThirdPartyMetadata({k: str(v) for k, v in third_party_metadata.items()}))
    if clear_flags:
        report["clear_flags"] = bool(c.ClearFlags(clear_flags))
    for flag in add_flags or []:
        report[f"flag:{flag}"] = bool(c.AddFlag(flag))
    if audio_mapping is not None:
        report["audio_mapping"] = bool(c.SetAudioMapping(audio_mapping))
    return report


@tool()
def set_clip_mark_in_out(ctx, clip: str, mark_in: int | None = None, mark_out: int | None = None, mark_type: MarkType = "all", clear: bool = False) -> Any:
    """Set (or clear) a media pool clip's mark in/out, in source frames."""
    c = ctx.clip(clip)
    if clear:
        check(c.ClearMarkInOut(mark_type), "clear marks")
    else:
        check(c.SetMarkInOut(mark_in, mark_out, mark_type), "set marks")
    return c.GetMarkInOut()


@tool("read")
def get_selected_clips(ctx) -> Any:
    """Clips selected in the media pool."""
    return [_clip_summary(c, props=("Type", "Duration")) for c in ctx.media_pool.GetSelectedClips() or []]


@tool()
def select_clip(ctx, clip: str) -> Any:
    """Select a clip in the media pool."""
    check(ctx.media_pool.SetSelectedClip(ctx.clip(clip)), "select clip")
    return {"ok": True}


@tool("destructive")
def delete_clips(ctx, clips: list[str]) -> Any:
    """Delete clips from the media pool (media on disk is untouched)."""
    check(ctx.media_pool.DeleteClips(ctx.clips(clips)), "delete clips")
    return {"ok": True}


@tool()
def move_clips(ctx, clips: list[str], target_bin: str) -> Any:
    """Move clips to another bin."""
    check(ctx.media_pool.MoveClips(ctx.clips(clips), ctx.folder(target_bin)), "move clips")
    return {"ok": True}


@tool()
def relink_clips(ctx, clips: list[str], folder_path: str | None = None, unlink: bool = False) -> Any:
    """Relink clips to media found under folder_path, or unlink them (unlink=true)."""
    mp = ctx.media_pool
    items = ctx.clips(clips)
    check(mp.UnlinkClips(items) if unlink else mp.RelinkClips(items, folder_path), "unlink clips" if unlink else "relink clips")
    return {"ok": True}


@tool()
def link_clip_media(ctx, clip: str, action: Literal["link_proxy", "unlink_proxy", "link_full_resolution", "replace", "replace_preserve_subclip", "monitor_growing_file"], path: str | None = None) -> Any:
    """Proxy and source media management for a clip: link/unlink a proxy file, link full-resolution
    media, replace the clip's media (optionally preserving sub-clip extents) or monitor a growing file."""
    c = ctx.clip(clip)
    fn = {
        "link_proxy": lambda: c.LinkProxyMedia(path),
        "unlink_proxy": lambda: c.UnlinkProxyMedia(),
        "link_full_resolution": lambda: c.LinkFullResolutionMedia(path),
        "replace": lambda: c.ReplaceClip(path),
        "replace_preserve_subclip": lambda: c.ReplaceClipPreserveSubClip(path),
        "monitor_growing_file": lambda: c.MonitorGrowingFile(),
    }[action]
    check(fn(), action)
    return {"ok": True}


@tool()
def create_multicam_clip(ctx, clips: list[str], options: dict[str, Any] | None = None) -> Any:
    """Create multicam clip(s). options (see get_api_type('MulticamOptions')): name, startTimecode,
    frameRate, angleSyncMode (MULTICAM_ANGLE_SYNC_*), angleNameMode (MULTICAM_ANGLE_NAME_*),
    multicamAudioMode (MULTICAM_AUDIO_*), detectSameCameraClipsMode (MULTICAM_DETECT_*), splitAtGaps,
    useFullClipExtents, createBinForSourceClips. Constant names are converted automatically."""
    return ctx.media_pool.CreateMulticamClip(ctx.clips(clips), ctx.consts_in(options or {}))


@tool()
def create_stereo_clip(ctx, left: str, right: str) -> Any:
    """Create a stereo 3D clip from a left-eye and a right-eye clip."""
    return check(ctx.media_pool.CreateStereoClip(ctx.clip(left), ctx.clip(right)), "create stereo clip")


@tool()
def auto_sync_audio(
    ctx,
    clips: list[str],
    sync_mode: Literal["waveform", "timecode", "in", "out", "marker"] = "waveform",
    channel: int | Literal["automatic", "mix"] = "automatic",
    retain_embedded_audio: bool = False,
    retain_video_metadata: bool = False,
) -> Any:
    """Sync video and audio clips (dual-system sound) by waveform, timecode, in/out points or markers."""
    r = ctx.resolve
    mode = {"waveform": r.AUDIO_SYNC_WAVEFORM, "timecode": r.AUDIO_SYNC_TIMECODE, "in": r.AUDIO_SYNC_IN, "out": r.AUDIO_SYNC_OUT, "marker": r.AUDIO_SYNC_MARKER}[sync_mode]
    ch = r.AUDIO_SYNC_CHANNEL_AUTOMATIC if channel == "automatic" else r.AUDIO_SYNC_CHANNEL_MIX if channel == "mix" else channel
    settings = {r.AUDIO_SYNC_MODE: mode, r.AUDIO_SYNC_CHANNEL_NUMBER: ch, r.AUDIO_SYNC_RETAIN_EMBEDDED_AUDIO: retain_embedded_audio, r.AUDIO_SYNC_RETAIN_VIDEO_METADATA: retain_video_metadata}
    check(ctx.media_pool.AutoSyncAudio(ctx.clips(clips), settings), "auto sync audio")
    return {"ok": True}


@tool()
def export_clip_metadata(ctx, path: str, clips: list[str] | None = None) -> Any:
    """Export clip metadata to a CSV file (all clips, or only `clips`)."""
    mp = ctx.media_pool
    check(mp.ExportMetadata(path, ctx.clips(clips)) if clips else mp.ExportMetadata(path), "export metadata")
    return {"path": path}


@tool()
def manage_mattes(
    ctx,
    action: Literal["list_clip", "add_clip", "delete_clip", "list_timeline", "add_timeline"],
    clip: str | None = None,
    paths: list[str] | None = None,
    stereo_eye: Literal["left", "right"] | None = None,
    bin: str | None = None,
) -> Any:
    """Clip mattes (attached to a clip) and timeline mattes (stand-alone, in a bin)."""
    mp = ctx.media_pool
    ms = ctx.resolve.GetMediaStorage()
    if action == "list_clip":
        return mp.GetClipMatteList(ctx.clip(clip))
    if action == "add_clip":
        c = ctx.clip(clip)
        check(ms.AddClipMattesToMediaPool(c, paths, stereo_eye) if stereo_eye else ms.AddClipMattesToMediaPool(c, paths), "add clip mattes")
        return mp.GetClipMatteList(c)
    if action == "delete_clip":
        check(mp.DeleteClipMattes(ctx.clip(clip), paths), "delete clip mattes")
        return {"ok": True}
    if action == "list_timeline":
        return mp.GetTimelineMatteList(ctx.folder(bin))
    return ms.AddTimelineMattesToMediaPool(paths)


AnalysisAction = Literal[
    "transcribe", "clear_transcription", "classify_audio", "clear_audio_classification",
    "intellisearch", "slate", "remove_motion_blur",
]


@tool()
def analyze_media(
    ctx,
    target: str,
    action: AnalysisAction,
    speaker_detection: bool | None = None,
    nested: bool = False,
    identify_faces: bool = False,
    better_quality: bool = False,
    slate_marker_color: str = "MARKER_BLUE",
    deblur_options: dict[str, Any] | None = None,
) -> Any:
    """AI analysis on a clip ("clip:...") or a whole bin ("folder:..."): transcription (with speaker
    detection, optionally of nested clips), audio classification, IntelliSearch indexing (faces),
    slate detection (marks with a MARKER_* color) or motion-blur removal (see
    get_api_type('DeblurOptions')). Some need Resolve Studio and downloaded AI extras."""
    obj = ctx.resolve_ref(target if ":" in target else f"clip:{target}")
    if action == "transcribe":
        ok = obj.TranscribeAudio(speaker_detection, nested) if speaker_detection is not None else obj.TranscribeAudio()
    elif action == "clear_transcription":
        ok = obj.ClearTranscription(nested) if nested and target.startswith("clip") else obj.ClearTranscription()
    elif action == "classify_audio":
        ok = obj.PerformAudioClassification()
    elif action == "clear_audio_classification":
        ok = obj.ClearAudioClassification()
    elif action == "intellisearch":
        ok = obj.AnalyzeForIntellisearch(identify_faces, better_quality)
    elif action == "slate":
        ok = obj.AnalyzeForSlate(ctx.const(slate_marker_color))
    else:
        result = obj.RemoveMotionBlur(deblur_options or {}) if deblur_options or target.startswith("clip") else obj.RemoveMotionBlur()
        return {"result": check(result, "remove motion blur")}
    check(ok, action)
    return {"ok": True}


@tool("read")
def get_transcription(ctx, clip: str, nested: bool = False) -> Any:
    """Transcription of a clip (language, segments with speaker, timing and words). Run
    analyze_media(action='transcribe') first."""
    c = ctx.clip(clip)
    return c.GetTranscription(nested) if nested else c.GetTranscription()
