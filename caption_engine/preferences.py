"""The single source of truth for user config: a root-level ``preferences.json``.

Everything the app persists between sessions lives here — app settings (last
language/preset/font/model, toggles) and the full preset library (built-in
seeds plus anything the user creates in the GUI).

On first run the file doesn't exist, so it's *seeded* from the built-in preset
factories in :mod:`caption_engine.presets.builtin`. After that, ``builtin.py``
is only used again for ``reset_to_defaults()``. A ``CaptionStyle`` serializes
via its existing ``to_dict()`` / ``from_dict()``.

Schema (version 1)::

    {
      "version": 1,
      "app": {last_language, last_preset, last_model, last_font,
              align, emoji, default_output_dir},
      "presets": {name: {<CaptionStyle.to_dict()>, "_group": "English"}},
      "preset_groups": {"English": [names...], "Uzbek": [names...]}
    }
"""
import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .style import CaptionStyle, find_system_font, list_available_fonts

SCHEMA_VERSION = 1

# preferences.py lives in caption_engine/, so the project root is one level up.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREFERENCES_PATH = _PROJECT_ROOT / "preferences.json"

# A write lock so concurrent web requests (Flask is threaded) never interleave
# a read-modify-write on the JSON file.
_LOCK = threading.RLock()


# ── seeding ──────────────────────────────────────────────────────────────────

def _default_app() -> dict:
    return {
        "last_language": "English",
        "last_preset": "reels_classic",
        "last_model": "large-v3",
        "last_font": "",
        "align": True,
        "emoji": True,
        "default_output_dir": "",
    }


def _seed() -> dict:
    """Build a fresh preferences dict from the built-in preset factories."""
    # Imported lazily to avoid a circular import (presets imports style, and we
    # want preferences importable very early).
    from .presets import builtin
    from .presets import PRESET_GROUPS

    presets: Dict[str, dict] = {}
    # Flatten the built-in factory functions, tagging each with its group.
    name_to_group = {}
    for group, names in PRESET_GROUPS.items():
        for n in names:
            name_to_group[n] = group

    factories = {
        "reels_classic": builtin.reels_classic,
        "bold_yellow_box": builtin.bold_yellow_box,
        "minimal_white": builtin.minimal_white,
        "punchy_green": builtin.punchy_green,
        "otg_cyan": builtin.otg_cyan,
        "gashtak_main": builtin.gashtak_main,
        "gashtak_2": builtin.gashtak_2,
    }
    for name, factory in factories.items():
        d = factory().to_dict()
        d["_group"] = name_to_group.get(name, "English")
        presets[name] = d

    return {
        "version": SCHEMA_VERSION,
        "app": _default_app(),
        "presets": presets,
        "preset_groups": {k: list(v) for k, v in PRESET_GROUPS.items()},
    }


# ── load / save ──────────────────────────────────────────────────────────────

def load() -> dict:
    """Return the preferences dict, creating (seeding) the file if missing.

    Missing top-level keys are backfilled so an older/edited file still works.
    """
    with _LOCK:
        if not PREFERENCES_PATH.exists():
            data = _seed()
            _write(data)
            return data
        try:
            data = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt file — reseed rather than crash the whole app.
            data = _seed()
            _write(data)
            return data

        seed = _seed()
        data.setdefault("version", SCHEMA_VERSION)
        # Backfill app keys without clobbering the user's values.
        app = data.setdefault("app", {})
        for k, v in _default_app().items():
            app.setdefault(k, v)
        # A file with no presets at all is treated as needing the seeds.
        if not data.get("presets"):
            data["presets"] = seed["presets"]
            data["preset_groups"] = seed["preset_groups"]
        data.setdefault("preset_groups", seed["preset_groups"])
        return data


def _write(data: dict) -> None:
    PREFERENCES_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save(data: dict) -> None:
    with _LOCK:
        _write(data)


def reset_to_defaults() -> dict:
    """Overwrite preferences.json with a fresh seed and return it."""
    with _LOCK:
        data = _seed()
        _write(data)
        return data


# ── app settings ─────────────────────────────────────────────────────────────

def get_app() -> dict:
    return load()["app"]


def set_app(updates: dict) -> dict:
    with _LOCK:
        data = load()
        data["app"].update(updates)
        _write(data)
        return data["app"]


# ── fonts ────────────────────────────────────────────────────────────────────

def _resolve_font(path: Optional[str]) -> str:
    """Validate a stored font path; fall back to a system default if it's gone.

    Accepts either an absolute path or a bare label from
    ``list_available_fonts()``. Returns an absolute path (or "" if nothing
    usable is found, which lets CaptionStyle apply its own default).
    """
    if path and os.path.exists(path):
        return path
    if path:
        # Maybe it's a display label rather than a path.
        fonts = list_available_fonts()
        if path in fonts:
            return fonts[path]
    return find_system_font()


# ── presets ──────────────────────────────────────────────────────────────────

def get_preset(name: str) -> CaptionStyle:
    """Instantiate a preset by name as a CaptionStyle. Raises ValueError if
    unknown."""
    data = load()
    presets = data.get("presets", {})
    if name not in presets:
        raise ValueError(
            f"Unknown preset '{name}'. Available: {list(presets.keys())}")
    d = dict(presets[name])
    d.pop("_group", None)
    d["font_path"] = _resolve_font(d.get("font_path"))
    return CaptionStyle.from_dict(d)


def list_presets() -> Dict[str, dict]:
    """Return {name: style_dict (with _group)} for every stored preset."""
    return load().get("presets", {})


def list_groups() -> Dict[str, List[str]]:
    """Return {language: [preset_name, ...]}. First name is that language's
    default."""
    return load().get("preset_groups", {})


def save_preset(name: str, style: CaptionStyle, group: str = "English") -> dict:
    """Create or update a preset. Appends it to the group's ordered list if new.
    Returns the updated preferences dict."""
    with _LOCK:
        data = load()
        d = style.to_dict()
        d["_group"] = group
        is_new = name not in data["presets"]
        data["presets"][name] = d

        groups = data.setdefault("preset_groups", {})
        members = groups.setdefault(group, [])
        if name not in members:
            members.append(name)
        # If the preset moved groups, drop it from any others.
        for g, names in groups.items():
            if g != group and name in names:
                names.remove(name)
        _write(data)
        return data


def delete_preset(name: str) -> dict:
    """Remove a preset from the library and every group list."""
    with _LOCK:
        data = load()
        data.get("presets", {}).pop(name, None)
        for names in data.get("preset_groups", {}).values():
            if name in names:
                names.remove(name)
        _write(data)
        return data
