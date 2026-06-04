"""Shared emoji detection helpers.

Both the layout splitter (`layout.builder`) and the renderer's font-switcher
(`renderer.text`) need to recognise emoji. They used to carry their own copies
of the codepoint ranges with a "keep these in sync" comment; this module is the
single source of truth so they can't drift.
"""
import re
from typing import List, Tuple

# Unicode ranges treated as emoji / pictographic symbols.
_RANGES = r"\U0001F000-\U0001FFFF\U00002600-\U000027BF"
_VS = "️"   # variation selector-16 (emoji presentation)
_ZWJ = "‍"  # zero-width joiner (used inside emoji sequences)

# A run of emoji, including ZWJ-joined sequences (e.g. 👨‍👩‍👧).
EMOJI_RE = re.compile(
    rf"[{_RANGES}{_VS}]+(?:{_ZWJ}[{_RANGES}{_VS}]+)*"
)

# A token made up *entirely* of emoji/symbol codepoints (incl. VS / ZWJ).
EMOJI_ONLY_RE = re.compile(rf"^[{_RANGES}{_VS}{_ZWJ}]+$")


def has_emoji(text: str) -> bool:
    """True if `text` contains at least one emoji run."""
    return bool(EMOJI_RE.search(text))


def is_emoji_only(text: str) -> bool:
    """True if `text` is non-empty and consists only of emoji codepoints.

    Such words decorate the preceding word and must not be bumped to their own
    line by the layout's char-count limit.
    """
    return bool(text) and bool(EMOJI_ONLY_RE.match(text))


def split_runs(text: str) -> List[Tuple[str, bool]]:
    """Split text into (segment, is_emoji) pairs for font-switching."""
    runs: List[Tuple[str, bool]] = []
    pos = 0
    for m in EMOJI_RE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False))
        runs.append((m.group(), True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False))
    return runs or [(text, False)]
