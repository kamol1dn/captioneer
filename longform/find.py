"""Phrase -> time on the long-form timeline, from word timings.

    python -m longform.find WORDS.json "phrase one" "phrase two" ...

WORDS.json is a list of {text, start, end} — ``whisperx.words.json`` from
``longform.transcribe``, or ``youtube.words.json`` from its ``--youtube``
mode. Prints every occurrence as start-end with a little context. Matching
ignores case and punctuation, so pass the words as heard.
"""
import json
import re
import sys
from pathlib import Path

_norm = lambda s: re.sub(r"[^a-z0-9$%]+", "", s.lower())


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find(words, phrase):
    toks = [_norm(w["text"]) for w in words]
    want = [t for t in (_norm(x) for x in phrase.split()) if t]
    return [(words[i]["start"], words[i + len(want) - 1]["end"], i)
            for i in range(len(toks) - len(want) + 1) if toks[i:i + len(want)] == want]


def mmss(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    words = load(sys.argv[1])
    for ph in sys.argv[2:]:
        hits = find(words, ph)
        if not hits:
            print(f"-- {ph!r}: not found")
        for s, e, i in hits:
            ctx = " ".join(w["text"] for w in words[max(0, i - 4): i + 12])
            print(f"{ph[:34]:34} {s:8.2f}-{e:8.2f}  [{mmss(s)}]  {ctx}")


if __name__ == "__main__":
    main()
