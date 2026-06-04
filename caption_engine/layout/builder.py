"""Group transcribed words into phrases (visible at once) and lines.

The layout is what determines the "feel" of the captions:
- Max chars per line keeps text readable on small screens
- Max lines visible controls how much text is on screen at once
- Phrase gaps create natural reading pauses
"""
from typing import List

from ..transcriber import Word
from ..style import CaptionStyle
from ..emoji import is_emoji_only
from .models import Line, Phrase


def _break_into_lines(words: List[Word], max_chars: int) -> List[Line]:
    """Pack words into lines.

    A word with `line_break=True` ends its line immediately — a manual break,
    e.g. at a sentence end. Otherwise words are greedily packed under max_chars.
    Emoji-only words never trigger an automatic break — they stay on the line of
    the word they follow, even if that nudges the line slightly over max_chars.
    """
    lines: List[Line] = []
    current = Line()
    for w in words:
        if current.words and is_emoji_only(w.text):
            # Keep a trailing emoji glued to the current line.
            current.words.append(w)
        else:
            prospective_len = current.char_count + (1 if current.words else 0) + len(w.text)
            if current.words and prospective_len > max_chars:
                lines.append(current)
                current = Line(words=[w])
            else:
                current.words.append(w)
        if w.line_break:
            lines.append(current)
            current = Line()
    if current.words:
        lines.append(current)
    return lines


def build_phrases(words: List[Word], style: CaptionStyle) -> List[Phrase]:
    """Convert flat word list into a sequence of Phrases.

    Algorithm:
    1. Split into "segments" on long gaps (silence between sentences)
    2. Within each segment, break words into lines by char count
    3. Within each segment, chunk lines into phrases by max_lines_visible
    """
    if not words:
        return []

    # 1. Split on big gaps
    segments: List[List[Word]] = [[]]
    for i, w in enumerate(words):
        if i > 0:
            gap = w.start - words[i - 1].end
            if gap > style.phrase_gap_threshold:
                segments.append([])
        segments[-1].append(w)

    phrases: List[Phrase] = []

    # 2 + 3. For each segment, break into lines, then chunk into phrases
    for seg_words in segments:
        if not seg_words:
            continue
        lines = _break_into_lines(seg_words, style.max_chars_per_line)

        # chunk lines into phrases of up to max_lines_visible
        n = style.max_lines_visible
        for i in range(0, len(lines), n):
            phrases.append(Phrase(lines=lines[i:i + n]))

    return phrases


def find_active_word_index(phrase: Phrase, t: float) -> int:
    """Return the index (into phrase.all_words) of the currently-active word,
    or -1 if none. A word is "active" while t is in [word.start, word.end].
    Between words we keep the previous one highlighted until the next starts."""
    words = phrase.all_words
    if not words:
        return -1
    if t < words[0].start:
        return -1
    for i, w in enumerate(words):
        if w.start <= t < w.end:
            return i
        # gap after this word, before next
        if i + 1 < len(words) and w.end <= t < words[i + 1].start:
            return i
    # past the end
    if t >= words[-1].end:
        return len(words) - 1
    return -1
