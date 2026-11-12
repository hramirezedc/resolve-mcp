"""Project manager: databases, project folders, projects, settings and cloud projects."""

from typing import Any

from ..app import tool
from ..refs import check


def _goto(pm, folder: str | None) -> None:
    """Navigate the project manager to `folder` ("/" or "" = root, "A/B" = path from root)."""
    if folder is None:
        return
    check(pm.GotoRootFolder(), "go to root project folder")
    for part in [p for p in folder.strip("/").split("/") if p]:
        check(pm.OpenFolder(part), f"open project folder {part!r}")


@tool("read")
def list_projects(ctx, folder: str | None = None, with_attributes: bool = False) -> Any:
    """Projects and sub-folders in the current project-manager folder, or in `folder` (a path from
    the root, "/" = root; navigating changes the current folder). Optionally with attributes
    (created / modified dates, notes, collaboration mode)."""
    pm = ctx.pm
    _goto(pm, folder)
    out: dict[str, Any] = {
        "current_folder": pm.GetCurrentFolder(),
        "folders": pm.GetFolderListInCurrentFolder(),
        "projects": pm.GetProjectListInCurrentFolder(),
    }
    if with_attributes:
        out["attributes"] = pm.GetProjectAttributesInCurrentFolder()
    return out


@tool()
def open_project(ctx, name: str, folder: str | None = None) -> Any:
    """Open (load) a project by name, optionally from a project-manager folder path."""
    pm = ctx.pm
    _goto(pm, folder)
    project = check(pm.LoadProject(name), f"load project {name!r}")
    return {"project": project, "timeline_count": project.GetTimelineCount()}


@tool()
def create_project(ctx, name: str, media_location: str | None = None, folder: str | None = None) -> Any:
    """Create and open a new project (optionally with a media location path, inside a folder)."""
    pm = ctx.pm
    _goto(pm, folder)
    project = pm.CreateProject(name, media_location) if media_location else pm.CreateProject(name)
    return {"project": check(project, f"create project {name!r} (does it already exist?)")}


@tool()
def save_project(ctx) -> Any:
    """Save the current project."""
    check(ctx.pm.SaveProject(), "save project")
    return {"ok": True}


@tool("destructive")
def close_project(ctx, save: bool = True) -> Any:
    """Close the current project (saving it first by default)."""
    pm = ctx.pm
    project = ctx.project
    if save:
        pm.SaveProject()
    check(pm.CloseProject(project), "close project")
    return {"ok": True}


@tool()
def rename_project(ctx, name: str) -> Any:
    """Rename the current project."""
    check(ctx.project.SetName(name), f"rename project to {name!r}")
    return {"project": ctx.project}


@tool("destructive")
def delete_project(ctx, name: str, folder: str | None = None) -> Any:
    """Delete a project from the database (it must not be open). Irreversible."""
    pm = ctx.pm
    _goto(pm, folder)
    check(pm.DeleteProject(name), f"delete project {name!r}")
    return {"ok": True}


@tool()
def import_project(ctx, path: str, name: str | None = None, restore_archive: bool = False) -> Any:
    """Import a .drp project file (or restore a .dra archive with restore_archive=true) into the
    current project-manager folder."""
    pm = ctx.pm
    if restore_archive:
        ok = pm.RestoreProject(path, name) if name else pm.RestoreProject(path)
    else:
        ok = pm.ImportProject(path, name) if name else pm.ImportProject(path)
    check(ok, f"import project {path}")
    return {"ok": True}


@tool()
def export_project(ctx, name: str, path: str, with_stills_and_luts: bool = True) -> Any:
    """Export a project of the current folder to a .drp file."""
    check(ctx.pm.ExportProject(name, path, with_stills_and_luts), f"export project {name!r}")
    return {"path": path}


@tool()
def archive_project(ctx, name: str, path: str, source_media: bool = True, render_cache: bool = False, proxy_media: bool = False) -> Any:
    """Archive a project to a .dra folder, optionally with source media, render cache and proxies."""
    check(ctx.pm.ArchiveProject(name, path, source_media, render_cache, proxy_media), f"archive project {name!r}")
    return {"path": path}


@tool()
def create_project_folder(ctx, name: str, parent: str | None = None) -> Any:
    """Create a project-manager folder in the current folder (or in `parent`)."""
    pm = ctx.pm
    _goto(pm, parent)
    check(pm.CreateFolder(name), f"create project folder {name!r}")
    return {"folders": pm.GetFolderListInCurrentFolder()}


@tool("destructive")
def delete_project_folder(ctx, name: str, parent: str | None = None) -> Any:
    """Delete a project-manager folder (and its projects) from the current folder or `parent`."""
    pm = ctx.pm
    _goto(pm, parent)
    check(pm.DeleteFolder(name), f"delete project folder {name!r}")
    return {"ok": True}


@tool("read")
def list_databases(ctx) -> Any:
    """Available project databases and the current one."""
    pm = ctx.pm
    return {"current": pm.GetCurrentDatabase(), "databases": pm.GetDatabaseList()}


@tool()
def set_database(ctx, db_name: str, db_type: str = "Disk", ip_address: str | None = None) -> Any:
    """Switch the project database (closes the open project). db_type is 'Disk' or 'PostgreSQL'."""
    info = {"DbType": db_type, "DbName": db_name}
    if ip_address:
        info["IpAddress"] = ip_address
    check(ctx.pm.SetCurrentDatabase(info), f"switch to database {db_name!r}")
    return {"current": ctx.pm.GetCurrentDatabase()}


@tool("read")
def get_project_settings(ctx, keys: list[str] | None = None) -> Any:
    """Project settings (all of them, or only `keys`, e.g. timelineFrameRate, timelineResolutionWidth,
    colorScienceMode...). See get_api_type('ProjectSettings') for every key and value."""
    settings = ctx.project.GetSettings() or {}
    return {k: settings.get(k) for k in keys} if keys else settings


@tool()
def set_project_settings(ctx, settings: dict[str, Any]) -> Any:
    """Set project settings from a {key: value} dict (see get_api_type('ProjectSettings')). If Resolve
    rejects the whole dict, keys are retried one by one and the failing ones reported.
    The 'superScale' 2x Enhanced mode needs execute_python: project.SetSetting('superScale', 2, sharpness, nr)."""
    project = ctx.project
    values = {k: (v if isinstance(v, str) else str(v) if not isinstance(v, bool) else ("1" if v else "0")) for k, v in settings.items()}
    if project.SetSettings(values):
        return {"ok": True, "applied": list(values)}
    report = {k: bool(project.SetSettings({k: v})) for k, v in values.items()}
    return {"ok": all(report.values()), "per_key": report}


@tool()
def cloud_project(
    ctx,
    action: str,
    project_name: str | None = None,
    media_path: str | None = None,
    is_collab: bool | None = None,
    sync_mode: str | None = None,
    camera_access: bool | None = None,
    path: str | None = None,
) -> Any:
    """Blackmagic Cloud projects. action: 'load', 'create', 'import' (from file `path`) or 'restore'
    (from folder `path`). sync_mode: CLOUD_SYNC_NONE, CLOUD_SYNC_PROXY_ONLY or CLOUD_SYNC_PROXY_AND_ORIG."""
    r = ctx.resolve
    settings: dict[Any, Any] = {}
    if project_name is not None:
        settings[r.CLOUD_SETTING_PROJECT_NAME] = project_name
    if media_path is not None:
        settings[r.CLOUD_SETTING_PROJECT_MEDIA_PATH] = media_path
    if is_collab is not None:
        settings[r.CLOUD_SETTING_IS_COLLAB] = is_collab
    if sync_mode is not None:
        settings[r.CLOUD_SETTING_SYNC_MODE] = ctx.const(sync_mode)
    if camera_access is not None:
        settings[r.CLOUD_SETTING_IS_CAMERA_ACCESS] = camera_access
    pm = ctx.pm
    if action == "load":
        return {"project": check(pm.LoadCloudProject(settings), "load cloud project")}
    if action == "create":
        return {"project": check(pm.CreateCloudProject(settings), "create cloud project")}
    if action == "import":
        return {"ok": check(pm.ImportCloudProject(path, settings), "import cloud project")}
    if action == "restore":
        return {"ok": check(pm.RestoreCloudProject(path, settings), "restore cloud project")}
    raise ValueError("action must be load, create, import or restore.")
