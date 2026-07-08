"""Build the AI-refinement prompt shown by the web UI.

The prompt text lives in ``caption_engine/prompts.txt`` (sections: english,
uzbek, emoji) so it can be tweaked without touching code. The file is re-read
on every call, so edits take effect on the next "Transcribe".
"""
import json
import re
from pathlib import Path

# prompts.txt sits next to this module at the package root.
_PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.txt"

_UZBEK_CODES = {"uz", "uzb", "uzbek"}
_SECTION_RE = re.compile(r"^\[\[(\w+)\]\]\s*$")


def _compact_words(words: list) -> list:
    """Slim word dicts for the prompt: only text + rounded start/end.

    `probability` and the always-false input `line_break` are dropped — they're
    noise the model can trip over (it's told to add line_break per the rules).
    3 decimals = millisecond precision, far finer than a video frame.
    """
    return [
        {"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
        for w in words
    ]


def _load_sections() -> dict:
    """Parse prompts.txt into {section_name: text}. Lines before the first
    [[section]] header (the file's comments) are ignored."""
    sections: dict = {}
    name = None
    buf: list = []
    for line in _PROMPTS_PATH.read_text(encoding="utf-8").splitlines():
        m = _SECTION_RE.match(line)
        if m:
            if name is not None:
                sections[name] = "\n".join(buf).strip()
            name = m.group(1).lower()
            buf = []
        elif name is not None:
            buf.append(line)
    if name is not None:
        sections[name] = "\n".join(buf).strip()
    return sections


def build_prompt(words: list, use_emojis: bool, language=None) -> str:
    """Render the refinement prompt for the given language and emoji setting.

    `language` "uz"/"uzbek" selects the Uzbek prompt; anything else (incl. None)
    uses the English one.
    """
    sections = _load_sections()
    key = "uzbek" if (language or "").lower() in _UZBEK_CODES else "english"
    try:
        template = sections[key]
        emoji_rules = sections["emoji"]
    except KeyError as e:
        raise KeyError(f"prompts.txt is missing the {e} section") from e

    # Leading newline so the emoji rules start on their own line right after the
    # last rule; empty (no extra line) when emojis are off.
    emoji_block = ("\n" + emoji_rules) if use_emojis else ""
    words_json = json.dumps(_compact_words(words), indent=2, ensure_ascii=False)

    # Plain replace (not str.format) so braces in the JSON or in user edits are
    # never interpreted as format fields.
    return (template
            .replace("{emoji_block}", emoji_block)
            .replace("{words_json}", words_json))
