"""Deliver page (render queue, formats, codecs, Quick Export) and Fairlight audio tools."""

from typing import Any, Literal

from ..app import tool
from ..refs import check


@tool("read")
def get_render_options(ctx, format: str | None = None, codec: str | None = None, audio: bool = False) -> Any:
    """Render formats (name -> extension), the codecs of `format` (an extension like 'mov'), the
    resolutions available for a format/codec, the current format/codec and render mode
    (0 = individual clips, 1 = single clip) and render presets. audio=true lists audio-only formats/codecs."""
    p = ctx.project
    out: dict[str, Any] = {
        "current": p.GetCurrentRenderFormatAndCodec(),
        "mode": p.GetCurrentRenderMode(),
        "presets": p.GetRenderPresetList(),
        "formats": p.GetAudioRenderFormats() if audio else p.GetRenderFormats(),
    }
    if format:
        out["codecs"] = p.GetAudioRenderCodecs(format) if audio else p.GetRenderCodecs(format)
        if not audio:
            out["resolutions"] = p.GetRenderResolutions(format, codec) if codec else p.GetRenderResolutions(format)
    return out


@tool()
def set_render_settings(
    ctx,
    preset: str | None = None,
    format: str | None = None,
    codec: str | None = None,
    mode: Literal["individual_clips", "single_clip"] | None = None,
    settings: dict[str, Any] | None = None,
) -> Any:
    """Prepare the Deliver page: load a render preset, set format + codec (e.g. 'mov' + 'ProRes422HQ'),
    render mode, and render settings such as TargetDir, CustomName, SelectAllFrames, MarkIn,
    MarkOut, FormatWidth, FormatHeight, FrameRate, VideoQuality, ExportAudio, ColorSpaceTag... (see
    get_api_type('RenderSettings')). Applied in that order."""
    p = ctx.project
    if preset:
        check(p.LoadRenderPreset(preset), f"load render preset {preset!r}")
    if format or codec:
        if not (format and codec):
            raise ValueError("Give both format and codec (see get_render_options).")
        check(p.SetCurrentRenderFormatAndCodec(format, codec), f"set format {format}/{codec}")
    if mode:
        check(p.SetCurrentRenderMode(0 if mode == "individual_clips" else 1), "set render mode")
    if settings:
        check(p.SetRenderSettings(ctx.consts_in(settings)), "set render settings (check key names with get_api_type('RenderSettings'))")
    return {"current": p.GetCurrentRenderFormatAndCodec(), "mode": p.GetCurrentRenderMode()}


@tool()
def add_render_job(ctx, timeline: str | int | None = None) -> Any:
    """Add a render job for a timeline (current by default) with the current Deliver settings.
    Returns its job id."""
    if timeline is not None:
        check(ctx.project.SetCurrentTimeline(ctx.timeline(timeline)), "select timeline")
    return {"job_id": check(ctx.project.AddRenderJob(), "add render job (are render settings valid?)")}


@tool("read")
def list_render_jobs(ctx) -> Any:
    """Render queue: every job with its settings and status."""
    p = ctx.project
    jobs = p.GetRenderJobList() or []
    for job in jobs:
        jid = job.get("JobId")
        if jid:
            job["status"] = p.GetRenderJobStatus(jid)
    return {"rendering": p.IsRenderingInProgress(), "jobs": jobs}


@tool("destructive")
def delete_render_jobs(ctx, job_ids: list[str] | None = None, all: bool = False) -> Any:
    """Delete render jobs by id, or all of them."""
    p = ctx.project
    if all:
        check(p.DeleteAllRenderJobs(), "delete all render jobs")
    else:
        for jid in job_ids or []:
            check(p.DeleteRenderJob(jid), f"delete job {jid}")
    return {"remaining": len(p.GetRenderJobList() or [])}


@tool()
def start_render(ctx, job_ids: list[str] | None = None, interactive: bool = False) -> Any:
    """Start rendering the given jobs (all queued jobs when omitted). interactive=true shows error
    dialogs in Resolve. Poll with render_status."""
    p = ctx.project
    ids = job_ids or [j.get("JobId") for j in p.GetRenderJobList() or [] if j.get("JobId")]
    if not ids:
        raise ValueError("No render jobs. Add one with add_render_job.")
    check(p.StartRendering(ids, interactive), "start rendering")
    return {"started": ids}


@tool()
def stop_render(ctx) -> Any:
    """Stop the render in progress."""
    ctx.project.StopRendering()
    return {"rendering": ctx.project.IsRenderingInProgress()}


@tool("read")
def render_status(ctx, job_id: str | None = None) -> Any:
    """Progress of one job, or of every job, plus whether a render is in progress."""
    p = ctx.project
    if job_id:
        return {"rendering": p.IsRenderingInProgress(), "status": p.GetRenderJobStatus(job_id)}
    return {"rendering": p.IsRenderingInProgress(), "jobs": {j["JobId"]: p.GetRenderJobStatus(j["JobId"]) for j in p.GetRenderJobList() or [] if j.get("JobId")}}


@tool()
def quick_export(ctx, preset: str, target_dir: str | None = None, custom_name: str | None = None, video_quality: int | None = None, enable_upload: bool | None = None, enable_preset: bool | None = None) -> Any:
    """Render the current timeline with a Quick Export preset (e.g. 'H.264', 'ProRes', 'YouTube').
    enable_preset toggles whether a render preset appears in Quick Export instead."""
    p = ctx.project
    if enable_preset is not None:
        check(p.SetQuickExportEnabledForRenderPreset(preset, enable_preset), "toggle Quick Export preset")
        return {"quick_export_presets": p.GetQuickExportRenderPresets()}
    info = {k: v for k, v in {"TargetDir": target_dir, "CustomName": custom_name, "VideoQuality": video_quality, "EnableUpload": enable_upload}.items() if v is not None}
    return p.RenderWithQuickExport(preset, info)


# --------------------------------------------------------------------------- Fairlight


@tool()
def insert_audio_at_playhead(ctx, path: str, start_offset_samples: int = 0, duration_samples: int = 0) -> Any:
    """Insert an audio file on the current audio track at the playhead (Fairlight page), optionally a
    sub-range in samples (duration 0 = whole file)."""
    check(ctx.project.InsertAudioToCurrentTrackAtPlayhead(path, start_offset_samples, duration_samples), "insert audio")
    return {"ok": True}


@tool()
def apply_fairlight_preset(ctx, preset: str) -> Any:
    """Apply a Fairlight preset (see list_presets('fairlight')) to the current timeline."""
    check(ctx.project.ApplyFairlightPresetToCurrentTimeline(preset), "apply Fairlight preset")
    return {"ok": True}


@tool()
def generate_speech(ctx, text: str, voice_model: str | None = None, custom_voice_file: str | None = None, speed: float | None = None, variation: float | None = None, pitch: float | None = None, filename: str | None = None, add_to_timeline: bool = False, audio_track: int | None = None) -> Any:
    """AI text-to-speech (Resolve Studio): creates a media pool clip, optionally placed on the timeline."""
    s: dict[str, Any] = {"TextInput": text, "AddToTimeline": add_to_timeline}
    for k, v in {"VoiceModel": voice_model, "CustomVoiceFile": custom_voice_file, "Speed": speed, "Variation": variation, "Pitch": pitch, "Filename": filename, "AudioTrack": audio_track}.items():
        if v is not None:
            s[k] = v
    return {"clip": check(ctx.project.GenerateSpeech(s), "generate speech")}


@tool()
def reset_intellisearch(ctx) -> Any:
    """Reset the project's IntelliSearch analysis."""
    check(ctx.project.ResetIntellisearchAnalysis(), "reset IntelliSearch")
    return {"ok": True}
