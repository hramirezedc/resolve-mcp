"""Application, API discovery, generic API calls and Python execution."""

import contextlib
import difflib
import io
import traceback
from typing import Any, Literal

from .. import api_index
from ..app import tool
from ..refs import check, type_of
from ._types import Page

# --------------------------------------------------------------------------- application


@tool("read")
def get_status(ctx) -> Any:
    """Resolve product/version, Studio flag, current page, database, project folder, open project,
    current timeline and playhead, keyframe mode and whether a render is running."""
    r = ctx.resolve
    pm = ctx.pm
    p = pm.GetCurrentProject()
    tl = p.GetCurrentTimeline() if p else None
    return {
        "product": r.GetProductName(),
        "version": r.GetVersionString(),
        "studio": r.IsStudio(),
        "page": r.GetCurrentPage(),
        "database": pm.GetCurrentDatabase(),
        "project_folder": pm.GetCurrentFolder(),
        "project": p.GetName() if p else None,
        "project_id": p.GetUniqueId() if p else None,
        "timeline_count": p.GetTimelineCount() if p else 0,
        "timeline": tl,
        "timecode": tl.GetCurrentTimecode() if tl else None,
        "keyframe_mode": r.GetKeyframeMode(),
        "rendering": bool(p and p.IsRenderingInProgress()),
    }


@tool()
def open_page(ctx, page: Page) -> Any:
    """Switch Resolve to a page: media, cut, edit, fusion, color, fairlight or deliver."""
    check(ctx.resolve.OpenPage(page), f"open page {page}")
    return {"page": ctx.resolve.GetCurrentPage()}


PresetKind = Literal["layout", "render", "burn_in", "keyboard", "fairlight", "user_preferences", "project_settings", "quick_export"]


@tool("read")
def list_presets(ctx, kind: PresetKind) -> Any:
    """List presets of one kind: layout, render, burn_in, keyboard (with the current one), fairlight,
    user_preferences, project_settings or quick_export."""
    r = ctx.resolve
    if kind == "layout":
        return r.GetLayoutPresetList()
    if kind == "render":
        return ctx.project.GetRenderPresetList()
    if kind == "burn_in":
        return r.GetBurnInPresetList()
    if kind == "keyboard":
        return {"presets": r.GetKeyboardPresetList(), "current": r.GetCurrentKeyboardPreset()}
    if kind == "fairlight":
        return r.GetFairlightPresets()
    if kind == "user_preferences":
        return r.GetUserPreferencesPresetList()
    if kind == "project_settings":
        return ctx.project.GetProjectSettingsPresetList()
    return ctx.project.GetQuickExportRenderPresets()


@tool()
def manage_preset(
    ctx,
    kind: Literal["layout", "render", "burn_in", "keyboard", "user_preferences", "project_settings"],
    action: Literal["load", "save", "update", "delete", "import", "export"],
    name: str | None = None,
    path: str | None = None,
) -> Any:
    """Load / save (as new, from current state) / update / delete / import (from `path`) / export
    (to `path`) a preset. Not every kind supports every action (e.g. render presets cannot be
    'loaded' here: use set_render_settings with preset=...)."""
    r, p = ctx.resolve, None
    try:
        p = ctx.project
    except LookupError:
        pass
    table = {
        ("layout", "load"): lambda: r.LoadLayoutPreset(name),
        ("layout", "save"): lambda: r.SaveLayoutPreset(name),
        ("layout", "update"): lambda: r.UpdateLayoutPreset(name),
        ("layout", "delete"): lambda: r.DeleteLayoutPreset(name),
        ("layout", "import"): lambda: r.ImportLayoutPreset(path, name) if name else r.ImportLayoutPreset(path),
        ("layout", "export"): lambda: r.ExportLayoutPreset(name, path),
        ("render", "load"): lambda: p.LoadRenderPreset(name),
        ("render", "save"): lambda: p.SaveAsNewRenderPreset(name),
        ("render", "update"): lambda: p.UpdateRenderPreset(name),
        ("render", "delete"): lambda: p.DeleteRenderPreset(name),
        ("render", "import"): lambda: r.ImportRenderPreset(path),
        ("render", "export"): lambda: r.ExportRenderPreset(name, path),
        ("burn_in", "load"): lambda: p.LoadBurnInPreset(name),
        ("burn_in", "delete"): lambda: r.DeleteBurnInPreset(name),
        ("burn_in", "import"): lambda: r.ImportBurnInPreset(path),
        ("burn_in", "export"): lambda: r.ExportBurnInPreset(name, path),
        ("keyboard", "load"): lambda: r.LoadKeyboardPreset(name),
        ("keyboard", "delete"): lambda: r.DeleteKeyboardPreset(name),
        ("keyboard", "import"): lambda: r.ImportKeyboardPreset(path, name) if name else r.ImportKeyboardPreset(path),
        ("keyboard", "export"): lambda: r.ExportKeyboardPreset(name, path),
        ("user_preferences", "load"): lambda: r.LoadUserPreferencesPreset(name),
        ("user_preferences", "save"): lambda: r.SaveUserPreferencesPreset(name),
        ("user_preferences", "delete"): lambda: r.DeleteUserPreferencesPreset(name),
        ("user_preferences", "import"): lambda: r.ImportUserPreferencesPreset(path, name) if name else r.ImportUserPreferencesPreset(path),
        ("user_preferences", "export"): lambda: r.ExportUserPreferencesPreset(name, path),
        ("project_settings", "load"): lambda: p.SetProjectSettingsPreset(name),
        ("project_settings", "save"): lambda: p.SaveCurrentProjectSettingsAsNewPreset(name),
        ("project_settings", "update"): lambda: p.UpdateProjectSettingsPreset(name),
        ("project_settings", "delete"): lambda: p.DeleteProjectSettingsPreset(name),
        ("project_settings", "import"): lambda: p.ImportProjectSettingsPreset(path, name) if name else p.ImportProjectSettingsPreset(path),
        ("project_settings", "export"): lambda: p.ExportProjectSettingsPreset(name, path),
    }
    fn = table.get((kind, action))
    if fn is None:
        raise ValueError(f"Action {action!r} is not available for {kind} presets.")
    if kind in ("render", "burn_in", "project_settings") and action not in ("import", "export") and p is None:
        raise LookupError("No project is open.")
    check(fn(), f"{action} {kind} preset {name or path}")
    return {"ok": True}


@tool()
def set_keyframe_mode(ctx, mode: Literal["all", "color", "sizing"]) -> Any:
    """Set the Color page keyframe mode."""
    r = ctx.resolve
    const = {"all": r.KEYFRAME_MODE_ALL, "color": r.KEYFRAME_MODE_COLOR, "sizing": r.KEYFRAME_MODE_SIZING}[mode]
    check(r.SetKeyframeMode(const), "set keyframe mode")
    return {"keyframe_mode": r.GetKeyframeMode()}


@tool()
def set_high_priority(ctx, enabled: bool) -> Any:
    """Give Resolve high process priority (e.g. while rendering)."""
    return {"ok": bool(ctx.resolve.SetHighPriority(enabled))}


@tool("read")
def validate_dctl(ctx, source: str) -> Any:
    """Compile-check DCTL source code. Returns null when valid, otherwise the error text."""
    return {"error": ctx.resolve.ValidateDCTL(source)}


@tool()
def encrypt_dctl(ctx, input_path: str, name: str | None = None, expiry: str | None = None, output_folder: str | None = None) -> Any:
    """Encrypt a .dctl file into a .dctle (optional output name, expiry date and output folder)."""
    opts = {k: v for k, v in {"Name": name, "Expiry": expiry, "OutputFolder": output_folder}.items() if v}
    check(ctx.resolve.EncryptDCTL(input_path, opts) if opts else ctx.resolve.EncryptDCTL(input_path), "encrypt DCTL")
    return {"ok": True}


@tool("destructive")
def disable_background_tasks(ctx) -> Any:
    """Disable Resolve background tasks (proxy, cache, analysis) for the rest of this Resolve session."""
    ctx.resolve.DisableBackgroundTasksForCurrentResolveSession()
    return {"ok": True}


@tool("destructive")
def quit_resolve(ctx) -> Any:
    """Quit DaVinci Resolve. Unsaved changes may be lost."""
    return {"ok": bool(ctx.resolve.Quit())}


# --------------------------------------------------------------------------- API discovery


@tool("read")
def list_api_methods(ctx, class_name: str | None = None) -> Any:
    """Every method of an API class with signature and documentation (Resolve 21.1 stubs).
    Without `class_name`, lists the classes."""
    if not class_name:
        return {c: len(api_index.methods(c)) for c in api_index.class_names()}
    return api_index.methods(class_name)


@tool("read")
def search_api(ctx, query: str, limit: int = 40) -> Any:
    """Search API methods, settings dictionaries and enum types by name or documentation text."""
    return api_index.search(query, limit)


@tool("read")
def get_api_type(ctx, name: str) -> Any:
    """Full definition of an API type: a settings dict (e.g. RenderSettings, ProjectSettings,
    TimelineItemProperties, ClipProperties, TimelineSettings), an enum alias or a class."""
    return api_index.describe_type(name)


@tool("read")
def get_api_docs(ctx, section: str = "TOC") -> Any:
    """Blackmagic's scripting README: 'TOC' for its headings, a heading name for one section
    (e.g. 'Audio Mapping', 'Looking up Project and Clip properties'), or '' for everything."""
    return api_index.docs(section)


@tool("read")
def list_constants(ctx, prefix: str = "") -> Any:
    """Resolve constants (name -> live value), optionally filtered by prefix, e.g. EXPORT_, CACHE_,
    AUTO_CAPTION_, COMPOSITE_, RETIME_, SCALE_, MARKER_, CLOUD_."""
    out = {}
    for name in api_index.constants(prefix):
        out[name] = getattr(ctx.resolve, name, None)
    return out


# --------------------------------------------------------------------------- generic calls


def _invoke(ctx, target: Any, method: str, args: list[Any], results: list[Any]) -> Any:
    def sub(v: Any) -> Any:
        if isinstance(v, dict) and set(v) == {"$result"}:
            i = v["$result"]
            if not isinstance(i, int) or not 0 <= i < len(results):
                raise ValueError(f"$result {i} does not refer to an earlier call.")
            return results[i]
        if isinstance(v, list):
            return [sub(x) for x in v]
        if isinstance(v, dict):
            return {k: sub(x) for k, x in v.items()}
        return v

    target = sub(target)
    obj = target if type_of(target) else ctx.resolve_ref(target)
    if not method or method.startswith("_"):
        raise ValueError("Invalid method name.")
    cls = type_of(obj)
    if cls in api_index.class_names() and cls not in ("Fusion", "FusionComp") and not api_index.has_method(cls, method):
        close = difflib.get_close_matches(method, list(api_index.methods(cls)), n=5)
        raise ValueError(f"{cls} has no method {method!r}. Close matches: {close}. Use list_api_methods('{cls}').")
    fn = getattr(obj, method, None)
    if fn is None:
        raise ValueError(f"{cls} has no attribute {method!r}.")
    call_args = [ctx.from_json(a) for a in sub(args or [])]
    return fn(*call_args) if callable(fn) else fn


@tool("destructive")
def call_api(ctx, target: str, method: str, args: list[Any] | None = None) -> Any:
    """Call ANY Resolve API method: `target` is a reference ("project", "media_pool", "timeline",
    "item:<uid>", "clip:<uid>", "graph:item:<uid>", "handle:<n>", ...), `method` the API method
    name (see list_api_methods) and `args` its positional arguments as JSON. Inside args, objects
    are {"$ref": "..."} and constants {"$const": "NAME"}. Returned objects come back as references."""
    return {"result": _invoke(ctx, target, method, args or [], [])}


@tool("destructive")
def call_api_batch(ctx, calls: list[dict[str, Any]], stop_on_error: bool = True) -> Any:
    """Run several API calls in order in one round trip. Each call is {"target", "method", "args"}.
    {"$result": i} (as target or anywhere in args) is the raw return value of call i (0-based), so
    calls can chain, e.g. target {"$result": 0} after a call that returned a timeline."""
    results: list[Any] = []
    report = []
    for i, call in enumerate(calls):
        try:
            value = _invoke(ctx, call.get("target"), call.get("method", ""), call.get("args") or [], results)
            results.append(value)
            report.append({"index": i, "result": value})
        except Exception as exc:
            results.append(None)
            report.append({"index": i, "error": f"{type(exc).__name__}: {exc}"})
            if stop_on_error:
                break
    return report


@tool("destructive")
def execute_python(ctx, code: str) -> Any:
    """Run arbitrary Python against Resolve when no tool fits. Pre-defined names: `resolve`,
    `project` (may be None), `media_pool`, `timeline` (current, may be None), `ctx` (lookup helpers:
    ctx.item(uid), ctx.clip(ref), ctx.folder(path), ctx.timeline(ref), ctx.graph(target)...).
    Assign to `result` to return a value (Resolve objects come back as references); stdout and
    stderr are captured. Full OS access: use with care."""
    project = ctx.pm.GetCurrentProject()
    env: dict[str, Any] = {
        "resolve": ctx.resolve,
        "project": project,
        "media_pool": project.GetMediaPool() if project else None,
        "timeline": project.GetCurrentTimeline() if project else None,
        "ctx": ctx,
        "result": None,
    }
    out, err = io.StringIO(), io.StringIO()
    error = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            exec(compile(code, "<execute_python>", "exec"), env)
        except Exception:
            error = traceback.format_exc()
    return {"result": env.get("result"), "stdout": out.getvalue()[-20000:], "stderr": err.getvalue()[-5000:], "error": error}
