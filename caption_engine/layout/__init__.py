"""Layout: turn a flat word list into on-screen Lines and Phrases."""
from .models import Line, Phrase
from .builder import build_phrases, find_active_word_index

__all__ = ["Line", "Phrase", "build_phrases", "find_active_word_index"]
