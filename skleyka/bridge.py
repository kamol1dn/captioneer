"""Python end of the file bridge to the Skleyka CEP panel (panel/main.js).

A command is one ExtendScript program: the helper library (jsx/*.jsx), then the
caller's body wrapped in a function that receives ``ARGS``. The body returns any
JSON-able value; the wrapper turns it, or the exception it threw, into the
``{"ok": ..., "data"|"error": ...}`` envelope the panel writes back.

Arguments are passed as a JSON literal inside the script rather than spliced
into code, so a file path with quotes or backslashes can't break the program.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

BRIDGE_DIR = Path(os.environ["LOCALAPPDATA"]) / "gashtak-skleyka" / "bridge"
HEARTBEAT = BRIDGE_DIR / "heartbeat.json"
JSX_DIR = Path(__file__).parent / "jsx"
STALE_S = 3.0


class BridgeError(RuntimeError):
    pass


def _helpers() -> str:
    # Read on every call so an edit to the .jsx takes effect without restarting
    # the MCP server; the files are small.
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(JSX_DIR.glob("*.jsx")))


def heartbeat() -> dict | None:
    """The panel's last heartbeat, or None if it is missing or stale."""
    try:
        hb = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() * 1000 - hb.get("at", 0) > STALE_S * 1000:
        return None
    return hb


def build_script(body: str, args: dict | None = None) -> str:
    return (
        "(function () {\n"
        + _helpers()
        + "\ntry {\n"
        + "var __value = (function (ARGS) {\n"
        + body
        + "\n})(" + json.dumps(args or {}, ensure_ascii=True) + ");\n"
        + 'return SK.json({ok: true, data: __value});\n'
        + "} catch (e) {\n"
        + 'return SK.json({ok: false, error: String(e) + (e.line ? " (line " + e.line + ")" : "")});\n'
        + "}\n})()"
    )


def run(body: str, args: dict | None = None, timeout: float = 60.0):
    """Run ``body`` in Premiere and return its value; raise BridgeError on failure."""
    if heartbeat() is None:
        raise BridgeError(
            "Skleyka bridge is not running in Premiere. Is Premiere open, and was "
            "the panel installed (skleyka/scripts/sign-panel.ps1) and "
            "Premiere restarted since?"
        )
    cid = f"{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    cmd = BRIDGE_DIR / f"cmd_{cid}.jsx"
    res = BRIDGE_DIR / f"res_{cid}.json"
    staged = BRIDGE_DIR / f"stage_{cid}.tmp"
    staged.write_text(build_script(body, args), encoding="utf-8")
    staged.replace(cmd)

    deadline = time.monotonic() + timeout
    while not res.exists():
        if time.monotonic() > deadline:
            # Unclaimed: withdraw it so it can't run later by surprise. Claimed
            # but unanswered: it may still be running, and may have changed
            # the project, so say so rather than pretending it failed cleanly.
            try:
                cmd.unlink()
                raise BridgeError(f"Premiere did not pick the command up within {timeout:.0f}s")
            except FileNotFoundError:
                raise BridgeError(
                    f"Premiere took the command but gave no answer within {timeout:.0f}s; "
                    "it may still be running — check the timeline before retrying"
                )
        time.sleep(0.05)

    raw = res.read_text(encoding="utf-8")
    res.unlink(missing_ok=True)
    try:
        envelope = json.loads(raw)
    except ValueError:
        raise BridgeError(f"Unreadable response: {raw[:300]}")
    if not envelope.get("ok"):
        raise BridgeError(envelope.get("error", "unknown error"))
    return envelope.get("data")
