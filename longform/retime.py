"""Move timed text (headline/name-bar specs, SRT) from one cut of an episode to another.

    python -m longform.retime OLD_WORDS NEW_WORDS SPEC.json [SPEC2.json ...] --out-dir DIR [--duration S]

The long-form text layers live outside the multicam, so trimming the edit
leaves them at the old times. Both cuts are transcribed (`longform.transcribe`
on the old and the new mix); the word sequences are aligned, and every timed
entry moves with the first word that survived after it. An entry whose whole
stretch was cut — it would land on the same moment as the next one — is
dropped. Each spec is rewritten into DIR with its `out` pointed there too.
"""
import argparse
import difflib
import json
import re
import sys
from bisect import bisect_left
from pathlib import Path

_norm = lambda s: re.sub(r"[^a-z0-9$%]+", "", s.lower())


def anchors(old_words, new_words):
    """(old_start, new_start) for every word matched between the two cuts, in order."""
    a = [_norm(w["text"]) for w in old_words]
    b = [_norm(w["text"]) for w in new_words]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    pairs = []
    for blk in sm.get_matching_blocks():
        # Short matches between cuts are usually coincidences ("the", "and").
        if blk.size < 3:
            continue
        for k in range(blk.size):
            pairs.append((old_words[blk.a + k]["start"], new_words[blk.b + k]["start"]))
    return pairs


def mapper(pairs):
    olds = [p[0] for p in pairs]

    def at(t):
        i = bisect_left(olds, t - 0.05)
        if i >= len(pairs):
            return None
        o, n = pairs[i]
        # Keep the entry's lead over its word, but never more than the word's own gap.
        lead = min(max(0.0, o - t), 2.0)
        return max(0.0, n - lead)

    return at


def retime(entries, at, min_gap=1.5):
    out = []
    for t, text in entries:
        nt = at(t)
        if nt is None:
            continue
        if out and nt - out[-1][0] < min_gap:
            # The previous entry's stretch was cut: the later one wins.
            out[-1] = [round(max(nt, out[-1][0]), 3), text]
            continue
        out.append([round(nt, 3), text])
    # Whatever opened the episode still opens it.
    if out and entries and entries[0][0] == 0:
        out[0][0] = 0.0
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m longform.retime")
    ap.add_argument("old_words")
    ap.add_argument("new_words")
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--duration", type=float, default=None, help="new sequence length, seconds")
    a = ap.parse_args()
    old = json.loads(Path(a.old_words).read_text(encoding="utf-8"))
    new = json.loads(Path(a.new_words).read_text(encoding="utf-8"))
    pairs = anchors(old, new)
    print(f"{len(pairs)} of {len(old)} old words matched in the new cut")
    at = mapper(pairs)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for sp in a.specs:
        spec = json.loads(Path(sp).read_text(encoding="utf-8"))
        before = spec["headlines"]
        spec["headlines"] = retime(before, at)
        if a.duration:
            spec["duration_s"] = a.duration
        spec["out"] = str(out_dir / Path(spec["out"]).name)
        dst = out_dir / Path(sp).name
        dst.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
        kept = {t for _, t in spec["headlines"]}
        dropped = [t for _, t in before if t not in kept]
        print(f"{Path(sp).name}: {len(spec['headlines'])} of {len(before)} kept -> {dst}")
        for t in dropped:
            print(f"   dropped (its stretch was cut): {t}")


if __name__ == "__main__":
    main()
