"""The Word data model and its JSON (de)serialization."""
from dataclasses import dataclass, asdict
from typing import List
import json
from pathlib import Path


@dataclass
class Word:
    """One transcribed word with timing."""
    text: str
    start: float   # seconds
    end: float     # seconds
    probability: float = 1.0
    line_break: bool = False   # if True, the on-screen line ends after this word

    def to_dict(self) -> dict:
        return asdict(self)


def save_words(words: List[Word], path: str) -> None:
    """Save word list to JSON. Useful for caching and for re-running renders
    without re-transcribing (slow part).

    The encoding is explicit because Windows defaults ``write_text`` to cp1252,
    which cannot represent emoji — and the refinement prompt asks the model to
    add them, so the very words most worth caching are the ones that would
    otherwise raise UnicodeEncodeError here.
    """
    data = [w.to_dict() for w in words]
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def load_words(path: str) -> List[Word]:
    """Load word list from JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Word(**d) for d in data]
