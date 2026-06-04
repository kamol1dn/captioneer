"""Layout data models: a Line of words and a Phrase of lines."""
from dataclasses import dataclass, field
from typing import List

from ..transcriber import Word


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
