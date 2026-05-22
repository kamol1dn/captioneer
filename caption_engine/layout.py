"""Layout: group transcribed words into phrases (visible at once) and lines.

The layout is what determines the "feel" of the captions:
- Max chars per line keeps text readable on small screens
- Max lines visible controls how much text is on screen at once
- Phrase gaps create natural reading pauses
"""
import re
from dataclasses import dataclass, field
from typing import List
from .transcriber import Word
from .style import CaptionStyle

# A word made up entirely of emoji/symbol codepoints (ranges kept in sync with
# renderer._EMOJI_RE). Such words decorate the preceding word and must not be
# bumped to their own line by the char-count limit.
_EMOJI_ONLY_RE = re.compile(
    r"^[\U0001F000-\U0001FFFF\U00002600-\U000027BF️‍]+$"
)


def _is_emoji_only(text: str) -> bool:
    return bool(text) and bool(_EMOJI_ONLY_RE.match(text))


@dataclass
class Line:
    """A single line of words shown together."""
    words: List[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


@dataclass
class Phrase:
    """A group of lines shown together (one "frame" of caption)."""
    lines: List[Line] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.lines[0].start

    @property
    def end(self) -> float:
        return self.lines[-1].end

    @property
    def all_words(self) -> List[Word]:
        return [w for line in self.lines for w in line.words]


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
        if current.words and _is_emoji_only(w.text):
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
