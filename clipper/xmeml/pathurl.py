"""Windows path -> the file:// URL form Premiere actually resolves.

``Path.as_uri()`` produces ``file:///D:/a/b.mp4``. Some Premiere builds accept
it; others silently import the clip as offline, which looks like a broken export
rather than a URL nit. Premiere's own FCP7 XML export writes
``file://localhost/D:/a/b.mp4``, so match that.

Percent-encoding has to run over UTF-8 bytes: unencoded Cyrillic/Uzbek
filenames are a common cause of offline media.
"""
from pathlib import Path
from urllib.parse import quote, unquote

# Keep the drive colon and separators literal; encode spaces and non-ASCII.
_SAFE = "/:"


def to_pathurl(path) -> str:
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        p = p.absolute()
    s = p.as_posix()

    if s.startswith("//"):                      # UNC: \\server\share\file
        return "file://" + quote(s[2:], safe=_SAFE, encoding="utf-8")
    return "file://localhost/" + quote(s, safe=_SAFE, encoding="utf-8")


def from_pathurl(url: str) -> Path:
    """Inverse of to_pathurl. Used by the XML round-trip test."""
    s = url
    for prefix in ("file://localhost/", "file:///", "file://"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return Path(unquote(s, encoding="utf-8"))
