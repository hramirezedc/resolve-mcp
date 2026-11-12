"""Addressing Resolve objects by stable references, and JSON (de)serialisation.

References are short strings an agent can keep and pass back:

    resolve | project_manager | project | media_pool | media_storage | gallery | fusion
    timeline                      current timeline
    timeline:<uid|name>           a timeline (an int index, 1-based, is also accepted by tools)
    item:<uid>                    a timeline item (clip, title, generator, transition...)
    clip:<uid|bin path|name>      a media pool item, e.g. "clip:Master/Day1/A001C003.mov"
    folder:<uid|bin path>         a media pool folder, e.g. "folder:Master/Day1" ("folder:" = root)
    graph:timeline[:<timeline>]   timeline node graph
    graph:item:<uid>[:<layer>]    a clip's node graph
    graph:group:<name>:pre|post   a color group's pre/post-clip graph
    color_group:<name>
    album:still:<n> | album:powergrade:<n> | album:current   (1-based)
    comp:<item uid>:<index|name>  a Fusion composition of a timeline item
    handle:<n>                    any other object returned by an earlier call

Any object returned by a tool is described as {"$ref": ..., "$type": ..., "name": ...}; that
dict (or just {"$ref": "..."}) can be passed back wherever an object is expected.
Resolve constants are passed as {"$const": "EXPORT_EDL"}.
"""

from __future__ import annotations

import collections
import math
from typing import Any, Iterator

TRACK_TYPES = ("video", "audio", "subtitle")
_SINGLETONS = {
    "Resolve": "resolve",
    "ProjectManager": "project_manager",
    "MediaPool": "media_pool",
    "MediaStorage": "media_storage",
    "Gallery": "gallery",
    "Project": "project",
}


def type_of(obj: Any) -> str | None:
    """Class name of a Resolve/Fusion remote object, or None for plain values."""
    if type(obj).__name__ != "PyRemoteObject":
        return None
    text = str(obj)
    return text.split(" ", 1)[0] if text else "Object"


class Ctx:
    """Per-call view of the running Resolve, with lookup helpers and an object-handle registry."""

    _handles: "collections.OrderedDict[int, Any]" = collections.OrderedDict()
    _next_handle = 1
    _item_cache: dict[str, Any] = {}
    _clip_cache: dict[str, Any] = {}

    def __init__(self, resolve: Any):
        self.resolve = resolve

    # ------------------------------------------------------------------ basics
    @property
    def pm(self) -> Any:
        return self.resolve.GetProjectManager()

    @property
    def project(self) -> Any:
        project = self.pm.GetCurrentProject()
        if not project:
            raise LookupError("No project is open in Resolve.")
        return project

    @property
    def media_pool(self) -> Any:
        return self.project.GetMediaPool()

    def const(self, name: str) -> Any:
        key = name.split(".", 1)[1] if name.startswith("resolve.") else name
        value = getattr(self.resolve, key, None)
        if value is None:
            raise ValueError(f"Unknown Resolve constant {name!r}. Use list_constants to see valid names.")
        return value

    # ------------------------------------------------------------------ timelines
    def timelines(self) -> list[Any]:
        project = self.project
        return [project.GetTimelineByIndex(i) for i in range(1, int(project.GetTimelineCount() or 0) + 1)]

    def timeline(self, ref: Any = None) -> Any:
        project = self.project
        if ref is None or ref == "" or ref == "current":
            tl = project.GetCurrentTimeline()
            if not tl:
                raise LookupError("No current timeline. Open one with set_current_timeline.")
            return tl
        if isinstance(ref, dict):
            return self.resolve_ref(ref)
        if isinstance(ref, int):
            tl = project.GetTimelineByIndex(ref)
            if not tl:
                raise LookupError(f"No timeline at index {ref} (1-based).")
            return tl
        ref = str(ref)
        if ref.startswith("timeline:"):
            ref = ref[len("timeline:"):]
            if not ref:
                return self.timeline(None)
        by_name = None
        for tl in self.timelines():
            if tl.GetUniqueId() == ref:
                return tl
            if by_name is None and tl.GetName() == ref:
                by_name = tl
        if by_name is not None:
            return by_name
        raise LookupError(f"Timeline {ref!r} not found. Use list_timelines.")

    @staticmethod
    def iter_items(tl: Any, track_type: str | None = None) -> Iterator[tuple[str, int, Any]]:
        for ttype in (track_type,) if track_type else TRACK_TYPES:
            for idx in range(1, int(tl.GetTrackCount(ttype) or 0) + 1):
                for item in tl.GetItemListInTrack(ttype, idx) or []:
                    yield ttype, idx, item

    def item(self, ref: Any, timeline: Any = None) -> Any:
        if isinstance(ref, dict):
            return self.resolve_ref(ref)
        uid = str(ref)
        if uid.startswith("item:"):
            uid = uid[5:]
        cached = self._item_cache.get(uid)
        if cached is not None:
            try:
                if cached.GetUniqueId() == uid:
                    return cached
            except Exception:
                pass
            self._item_cache.pop(uid, None)
        order = []
        try:
            order.append(self.timeline(timeline))
        except LookupError:
            if timeline is not None:
                raise
        order += [t for t in self.timelines() if not order or t.GetUniqueId() != order[0].GetUniqueId()]
        for tl in order:
            for _, _, item in self.iter_items(tl):
                iid = item.GetUniqueId()
                self._item_cache[iid] = item
                if iid == uid:
                    return item
        raise LookupError(f"Timeline item {uid!r} not found. Use list_track_items to get item ids.")

    def items(self, refs: list[Any], timeline: Any = None) -> list[Any]:
        return [self.item(r, timeline) for r in refs]

    # ------------------------------------------------------------------ media pool
    def walk_folders(self, folder: Any = None, path: str | None = None) -> Iterator[tuple[str, Any]]:
        folder = folder or self.media_pool.GetRootFolder()
        path = path if path is not None else folder.GetName()
        yield path, folder
        for sub in folder.GetSubFolderList() or []:
            yield from self.walk_folders(sub, f"{path}/{sub.GetName()}")

    def folder(self, ref: Any = None) -> Any:
        if isinstance(ref, dict):
            return self.resolve_ref(ref)
        mp = self.media_pool
        root = mp.GetRootFolder()
        path = "" if ref is None else str(ref)
        if path.startswith("folder:"):
            path = path[7:]
        path = path.strip().strip("/")
        if path in ("", "root") or path == root.GetName():
            return root
        if path == "current":
            return mp.GetCurrentFolder()
        parts = path.split("/")
        if parts[0] == root.GetName():
            parts = parts[1:]
        node = root
        for part in parts:
            node = next((f for f in node.GetSubFolderList() or [] if f.GetName() == part), None)
            if node is None:
                break
        if node is not None:
            return node
        for _, f in self.walk_folders():
            if f.GetUniqueId() == path:
                return f
        raise LookupError(f"Media pool folder {ref!r} not found. Use get_media_pool_tree.")

    def folder_path(self, folder: Any) -> str:
        uid = folder.GetUniqueId()
        for path, f in self.walk_folders():
            if f.GetUniqueId() == uid:
                return path
        return folder.GetName()

    def iter_clips(self, folder: Any = None, recursive: bool = True) -> Iterator[tuple[str, Any]]:
        folders = self.walk_folders(folder, None if folder is None else self.folder_path(folder))
        if not recursive:
            folder = folder or self.media_pool.GetRootFolder()
            folders = iter([(self.folder_path(folder), folder)])
        for path, f in folders:
            for clip in f.GetClipList() or []:
                yield path, clip

    def clip(self, ref: Any) -> Any:
        if isinstance(ref, dict):
            return self.resolve_ref(ref)
        key = str(ref)
        if key.startswith("clip:"):
            key = key[5:]
        cached = self._clip_cache.get(key)
        if cached is not None:
            try:
                if cached.GetUniqueId() == key:
                    return cached
            except Exception:
                pass
            self._clip_cache.pop(key, None)
        by_name = []
        for path, clip in self.iter_clips():
            uid = clip.GetUniqueId()
            self._clip_cache[uid] = clip
            name = clip.GetName()
            if uid == key or f"{path}/{name}" == key:
                return clip
            if name == key:
                by_name.append(clip)
        if len(by_name) == 1:
            return by_name[0]
        if by_name:
            raise LookupError(f"{len(by_name)} clips are named {key!r}; use the clip id or its bin path.")
        raise LookupError(f"Media pool clip {ref!r} not found. Use list_clips.")

    def clips(self, refs: list[Any]) -> list[Any]:
        return [self.clip(r) for r in refs]

    # ------------------------------------------------------------------ color
    def color_group(self, name: str) -> Any:
        if name.startswith("color_group:"):
            name = name[12:]
        for group in self.project.GetColorGroupsList() or []:
            if group.GetName() == name:
                return group
        raise LookupError(f"Color group {name!r} not found. Use list_color_groups.")

    def graph(self, target: str, layer: int | None = None) -> Any:
        """Node graph of 'timeline[:<tl>]', 'item:<uid>' or 'group:<name>:pre|post' (graph: prefix optional)."""
        if target.startswith("graph:"):
            target = target[6:]
        if target == "timeline" or target.startswith("timeline:"):
            graph = self.timeline(target if target != "timeline" else None).GetNodeGraph()
        elif target.startswith("item:") or ":" not in target:
            parts = target.split(":")
            uid = parts[1] if parts[0] == "item" else parts[0]
            if len(parts) > 2 and layer is None:
                layer = int(parts[2])
            item = self.item(uid)
            graph = item.GetNodeGraph(layer) if layer is not None else item.GetNodeGraph()
        elif target.startswith("group:"):
            _, rest = target.split(":", 1)
            name, _, which = rest.rpartition(":")
            if which not in ("pre", "post"):
                raise ValueError("Color group graph targets look like 'group:<name>:pre' or 'group:<name>:post'.")
            group = self.color_group(name)
            graph = group.GetPreClipNodeGraph() if which == "pre" else group.GetPostClipNodeGraph()
        else:
            raise ValueError(f"Unknown graph target {target!r}: use 'timeline', 'item:<uid>' or 'group:<name>:pre|post'.")
        if not graph:
            raise LookupError(f"No node graph for {target!r} (is the Color page available for it?).")
        return graph

    def album(self, ref: str) -> Any:
        gallery = self.project.GetGallery()
        if ref.startswith("album:"):
            ref = ref[6:]
        if ref == "current":
            return gallery.GetCurrentStillAlbum()
        kind, _, idx = ref.partition(":")
        albums = gallery.GetGalleryStillAlbums() if kind == "still" else gallery.GetGalleryPowerGradeAlbums() if kind == "powergrade" else None
        if albums is None or not idx.isdigit():
            raise ValueError("Album references look like 'album:still:1', 'album:powergrade:1' or 'album:current'.")
        i = int(idx)
        if not 1 <= i <= len(albums or []):
            raise LookupError(f"No {kind} album #{i}; there are {len(albums or [])}.")
        return albums[i - 1]

    def comp(self, ref: str) -> Any:
        if ref.startswith("comp:"):
            ref = ref[5:]
        uid, _, which = ref.partition(":")
        item = self.item(uid)
        comp = item.GetFusionCompByIndex(int(which)) if which.isdigit() else item.GetFusionCompByName(which) if which else item.GetFusionCompByIndex(1)
        if not comp:
            raise LookupError(f"No Fusion composition {which or 1!r} on item {uid}.")
        return comp

    # ------------------------------------------------------------------ references
    def handle(self, obj: Any) -> str:
        cls = type(self)
        n = cls._next_handle
        cls._next_handle += 1
        cls._handles[n] = obj
        while len(cls._handles) > 20000:
            cls._handles.popitem(last=False)
        return f"handle:{n}"

    def resolve_ref(self, ref: Any) -> Any:
        if isinstance(ref, dict):
            if "$const" in ref:
                return self.const(ref["$const"])
            ref = ref.get("$ref")
            if ref is None:
                raise ValueError("Object references are {'$ref': '...'}")
        ref = str(ref)
        head, _, rest = ref.partition(":")
        simple = {
            "resolve": lambda: self.resolve,
            "project_manager": lambda: self.pm,
            "pm": lambda: self.pm,
            "project": lambda: self.project,
            "media_pool": lambda: self.media_pool,
            "media_storage": lambda: self.resolve.GetMediaStorage(),
            "gallery": lambda: self.project.GetGallery(),
            "fusion": lambda: self.resolve.Fusion(),
            "root_folder": lambda: self.media_pool.GetRootFolder(),
            "current_folder": lambda: self.media_pool.GetCurrentFolder(),
        }
        if head in simple and not rest:
            return simple[head]()
        if head == "timeline":
            return self.timeline(rest or None)
        if head == "item":
            return self.item(rest)
        if head == "clip":
            return self.clip(rest)
        if head == "folder":
            return self.folder(rest)
        if head == "graph":
            return self.graph(rest)
        if head == "color_group":
            return self.color_group(rest)
        if head == "album":
            return self.album(rest)
        if head == "comp":
            return self.comp(rest)
        if head == "handle" and rest.isdigit():
            obj = self._handles.get(int(rest))
            if obj is None:
                raise LookupError(f"Handle {ref} expired; fetch the object again.")
            return obj
        raise ValueError(f"Unknown reference {ref!r}. See the server instructions for reference formats.")

    def describe(self, obj: Any) -> dict[str, Any]:
        kind = type_of(obj) or "Object"
        out: dict[str, Any] = {"$type": kind}
        try:
            if kind in ("Timeline", "TimelineItem", "MediaPoolItem", "Folder"):
                uid = obj.GetUniqueId()
                prefix = {"Timeline": "timeline", "TimelineItem": "item", "MediaPoolItem": "clip", "Folder": "folder"}[kind]
                out["$ref"] = f"{prefix}:{uid}"
                out["name"] = obj.GetName()
                if kind == "TimelineItem":
                    self._item_cache[uid] = obj
                elif kind == "MediaPoolItem":
                    self._clip_cache[uid] = obj
                return out
            if kind in _SINGLETONS:
                out["$ref"] = _SINGLETONS[kind]
                if kind == "Project":
                    out["name"] = obj.GetName()
                return out
            if kind == "ColorGroup":
                out["name"] = obj.GetName()
                out["$ref"] = f"color_group:{out['name']}"
                return out
        except Exception:
            pass
        out["$ref"] = self.handle(obj)
        return out

    # ------------------------------------------------------------------ JSON
    def to_json(self, value: Any, depth: int = 0) -> Any:
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, (list, tuple)):
            return [self.to_json(v, depth + 1) for v in value]
        if isinstance(value, dict):
            return {str(k): self.to_json(v, depth + 1) for k, v in value.items()}
        if type_of(value):
            return self.describe(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return str(value)

    def consts_in(self, value: Any) -> Any:
        """Replace string values that name a Resolve constant (e.g. "AUDIO_SYNC_WAVEFORM") by its value."""
        if isinstance(value, dict):
            return {k: self.consts_in(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.consts_in(v) for v in value]
        if isinstance(value, str) and value.isupper() and "_" in value:
            const = getattr(self.resolve, value.split(".", 1)[-1], None)
            if isinstance(const, (int, float)):
                return const
        return value

    def from_json(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self.from_json(v) for v in value]
        if isinstance(value, dict):
            if "$ref" in value or "$const" in value:
                return self.resolve_ref(value)
            return {k: self.from_json(v) for k, v in value.items()}
        return value


def check(ok: Any, what: str) -> Any:
    """Raise when a Resolve call reports failure (False / None)."""
    if ok is False or ok is None:
        raise RuntimeError(f"Resolve refused: {what}")
    return ok
