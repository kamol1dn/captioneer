"""Where a project lives, plus safe JSON writes.

Projects are **colocated with their media**: drop the synced camera exports in
an episode folder and the project directory is created as ``clipper/`` right
beside them. The whole episode — media, transcripts, EDL, exported XML — is
then one self-contained folder you can move, copy to another drive, or archive
without breaking anything (camera paths are stored relative, see project.py).

Because projects are scattered across drives rather than sitting under one
root, a small registry maps project id -> directory so tools can still say
"project 2026-07-21_ep12" instead of a full path. The registry is a cache, not
the source of truth: every project directory is fully self-describing, so a
lost or stale registry costs you a lookup, never data. Anywhere a project id is
accepted, a path to the project directory works too.

Write discipline follows ``caption_engine/preferences.py``: RLock plus atomic
replace. It matters more here — the MCP server writes ``edl.json`` while you may
have it open in an editor, and a half-written EDL loses an editing session.
"""
import json
import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.RLock()

# Subfolder created next to the media for a colocated project.
PROJECT_DIRNAME = "clipper"


def registry_path() -> Path:
    """The id -> directory index. Override with CLIPPER_REGISTRY."""
    env = os.environ.get("CLIPPER_REGISTRY")
    return Path(env) if env else _REPO_ROOT / "clipper_projects.json"


def projects_root() -> Optional[Path]:
    """Legacy/explicit central root, only if CLIPPER_PROJECTS_DIR is set.

    Setting it forces every new project under one directory instead of beside
    its media — useful if the footage lives on a drive you'd rather not write
    to. Unset (the default) means colocated.
    """
    env = os.environ.get("CLIPPER_PROJECTS_DIR")
    return Path(env) if env else None


def default_project_dir(media_paths: List[str], project_id: str) -> Path:
    """Where a new project should live, given its camera files.

    Colocated by default: the common parent of the media plus ``clipper/``. All
    cameras normally sit in one folder, so that's just ``<that folder>/clipper``.
    If the cameras are scattered across different roots there is no sensible
    shared parent, so fall back to a central root keyed by project id.
    """
    forced = projects_root()
    if forced:
        return forced / project_id

    parents = {Path(p).resolve().parent for p in media_paths}
    if len(parents) == 1:
        return next(iter(parents)) / PROJECT_DIRNAME

    try:
        common = Path(os.path.commonpath([str(p) for p in parents]))
        return common / PROJECT_DIRNAME
    except ValueError:
        # Different drives on Windows — commonpath raises rather than guessing.
        return _REPO_ROOT / "projects" / project_id


# ── registry ─────────────────────────────────────────────────────────────────

def read_registry() -> Dict[str, str]:
    return read_json(registry_path(), {}) or {}


def register(project_id: str, project_dir: Path) -> None:
    with _LOCK:
        reg = read_registry()
        reg[project_id] = str(Path(project_dir).resolve())
        write_json_atomic(registry_path(), reg)


def unregister(project_id: str) -> None:
    with _LOCK:
        reg = read_registry()
        if reg.pop(project_id, None) is not None:
            write_json_atomic(registry_path(), reg)


def resolve_project_dir(id_or_path: str) -> Optional[Path]:
    """Accept a project id or a path to the project directory (or its parent).

    Checked in order: a literal directory containing project.json, that
    directory's ``clipper/`` subfolder (so you can point at the media folder),
    then the registry.
    """
    candidate = Path(id_or_path)
    if candidate.is_dir():
        if (candidate / "project.json").exists():
            return candidate.resolve()
        nested = candidate / PROJECT_DIRNAME
        if (nested / "project.json").exists():
            return nested.resolve()

    known = read_registry().get(id_or_path)
    if known and (Path(known) / "project.json").exists():
        return Path(known)

    forced = projects_root()
    if forced and (forced / id_or_path / "project.json").exists():
        return (forced / id_or_path).resolve()

    legacy = _REPO_ROOT / "projects" / id_or_path
    if (legacy / "project.json").exists():
        return legacy.resolve()
    return None


def known_project_dirs() -> List[Path]:
    """Every registered project directory that still exists on disk."""
    out = []
    for pid, path in read_registry().items():
        p = Path(path)
        if (p / "project.json").exists():
            out.append(p)
    return out


# ── misc ─────────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """Filesystem-safe project id. Keeps unicode letters (Uzbek names)."""
    s = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s or "untitled"


def write_json_atomic(path: Path, data) -> None:
    """Write JSON via a temp file + os.replace, so readers never see a partial."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, path)


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with _LOCK:
        return json.loads(path.read_text(encoding="utf-8"))


def mtime(path: Path) -> Optional[float]:
    """Modification time, or None if absent. Used for clobber detection."""
    p = Path(path)
    return p.stat().st_mtime if p.exists() else None
