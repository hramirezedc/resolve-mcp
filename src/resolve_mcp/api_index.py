"""Index of the Resolve scripting API, read from the bundled type stubs (Resolve 21.1)."""

from __future__ import annotations

import ast
import functools
import os
import sys
from pathlib import Path
from typing import Any

# Blackmagic ships the stubs and the README with Resolve (Developer/Scripting); they are read
# from the local installation, not redistributed with this package.
DEFAULT_API_DIRS = {
    "darwin": "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    "win32": os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting"),
    "linux": "/opt/resolve/Developer/Scripting",
}


def _api_file(name: str) -> Path:
    candidates = [os.environ.get("RESOLVE_SCRIPT_API"), DEFAULT_API_DIRS.get(sys.platform), str(Path(__file__).parent / "api")]
    for base in candidates:
        if base and (Path(base) / name).is_file():
            return Path(base) / name
    raise LookupError(
        f"{name} not found in the Resolve Developer/Scripting folder. Install DaVinci Resolve 21+ "
        "or set RESOLVE_SCRIPT_API to the folder that contains it."
    )


@functools.cache
def _index() -> dict[str, Any]:
    source = _api_file("DaVinciResolveScript.pyi").read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes: dict[str, Any] = {}
    typeddicts: dict[str, str] = {}
    aliases: dict[str, str] = {}
    constants: dict[str, str] = {}
    body = tree.body
    for i, node in enumerate(body):
        if isinstance(node, ast.ClassDef):
            is_td = any(getattr(b, "id", "") == "TypedDict" for b in node.bases)
            if is_td:
                typeddicts[node.name] = ast.get_source_segment(source, node) or ""
                continue
            methods = {}
            for f in node.body:
                if isinstance(f, ast.FunctionDef):
                    args = [a for a in f.args.args if a.arg != "self"]
                    defaults = [None] * (len(args) - len(f.args.defaults)) + list(f.args.defaults)
                    parts = []
                    for a, d in zip(args, defaults):
                        text = a.arg + (": " + ast.unparse(a.annotation) if a.annotation else "")
                        if d is not None:
                            text += " = " + ast.unparse(d)
                        parts.append(text)
                    ret = " -> " + ast.unparse(f.returns) if f.returns else ""
                    methods[f.name] = {"signature": f"{f.name}({', '.join(parts)}){ret}", "doc": ast.get_docstring(f) or ""}
                elif isinstance(f, ast.AnnAssign) and node.name == "Resolve":
                    constants[f.target.id] = ast.unparse(f.annotation)
            classes[node.name] = {"doc": ast.get_docstring(node) or "", "methods": methods}
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            name = getattr(target, "id", None)
            if not name:
                continue
            text = ast.get_source_segment(source, node) or ""
            nxt = body[i + 1] if i + 1 < len(body) else None
            if isinstance(nxt, ast.Expr) and isinstance(getattr(nxt, "value", None), ast.Constant) and isinstance(nxt.value.value, str):
                text += "\n" + nxt.value.value
            aliases[name] = text
    return {"classes": classes, "typeddicts": typeddicts, "aliases": aliases, "constants": constants}


def class_names() -> list[str]:
    return sorted(_index()["classes"])


def methods(class_name: str) -> dict[str, dict[str, str]]:
    classes = _index()["classes"]
    if class_name not in classes:
        raise LookupError(f"Unknown class {class_name!r}. Classes: {', '.join(class_names())}")
    return classes[class_name]["methods"]


def has_method(class_name: str, method: str) -> bool:
    return method in _index()["classes"].get(class_name, {}).get("methods", {})


def describe_type(name: str) -> str:
    idx = _index()
    if name in idx["typeddicts"]:
        return idx["typeddicts"][name]
    if name in idx["aliases"]:
        return idx["aliases"][name]
    if name in idx["classes"]:
        c = idx["classes"][name]
        lines = [f"class {name}: {c['doc']}"]
        for m in c["methods"].values():
            doc = m["doc"].splitlines()[0] if m["doc"] else ""
            lines.append(f"  {m['signature']}  # {doc}")
        return "\n".join(lines)
    raise LookupError(f"Unknown API type {name!r}. Try search_api.")


def constants(prefix: str = "") -> dict[str, str]:
    prefix = prefix.upper()
    return {k: v for k, v in _index()["constants"].items() if k.startswith(prefix)}


def search(query: str, limit: int = 40) -> list[dict[str, str]]:
    q = query.lower()
    out = []
    idx = _index()
    for cname, c in idx["classes"].items():
        for mname, m in c["methods"].items():
            if q in mname.lower() or q in m["doc"].lower():
                out.append({"class": cname, "method": mname, "signature": m["signature"], "doc": m["doc"][:300]})
    for name, text in {**idx["typeddicts"], **idx["aliases"]}.items():
        if q in name.lower() or q in text.lower():
            out.append({"type": name, "doc": text[:300]})
    return out[:limit]


def docs(section: str = "TOC") -> str:
    """The Resolve scripting README: its table of contents, one section, or ("") all of it."""
    text = _api_file("README.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    heads = [(i, len(l) - len(l.lstrip("#")), l.lstrip("#").strip()) for i, l in enumerate(lines) if l.startswith("#") and not l.startswith("#!")]
    if section == "":
        return text
    if section.upper() == "TOC":
        return "\n".join("  " * (lvl - 1) + title for _, lvl, title in heads)
    q = section.lower()
    match = next((h for h in heads if h[2].lower() == q), None) or next((h for h in heads if q in h[2].lower()), None)
    if match is None:
        raise LookupError(f"No section {section!r}. Call with section='TOC' for the list.")
    start, level, _ = match
    end = next((i for i, lvl, _ in heads if i > start and lvl <= level), len(lines))
    return "\n".join(lines[start:end])
