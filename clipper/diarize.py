"""Per-mic transcripts -> one speaker-labelled timeline.

Transcribing the combined mix gives you the words but not who said them. The
energy envelope answers that after the fact, per utterance, and it cannot
represent two people talking at once: the mix has a single word stream, so an
overlap comes back as one speaker's words, a garble, or nothing.

Transcribing each mic separately fixes both — and introduces one problem. Every
mic hears the whole room, so each transcript also contains the *other* speaker,
20-40 dB down (bleed). Merge N transcripts naively and every line appears N
times.

Bleed rejection is therefore per **word**, not per utterance: for each word, ask
which mic was loudest at that instant, and keep the word only if the mic it came
from is the one that won. An utterance survives if enough of its words did.
Doing this per word rather than per utterance is precisely what lets genuine
simultaneous speech live on both mics — the whole reason for transcribing them
separately — because a speaker stays dominant on their own mic even while
someone else is talking over them.

Two knobs, both deliberately forgiving:

* ``margin`` — a word counts as "won" when its own mic is within this many
  points of the loudest. Near-ties are kept on both mics rather than arbitrated,
  since a near-tie is what crosstalk actually looks like.
* ``keep_ratio`` — the fraction of an utterance's words that must have won.
  Below half means the utterance is mostly someone else's voice.

**Everything here is keyed by speaker, never by camera.** One person may own two
cameras — a second angle to cut to instead of a jump cut — and their two mics
carry the same voice within a decibel or two of each other. Fed in as separate
rivals they would both clear the margin on every word, so every line that person
said would survive twice and land in the master timeline twice. The caller
therefore hands in one transcript per speaker (``Project.transcription_mic``) and
envelopes merged per speaker (``energy.group_by_speaker``); the near-tie
forgiveness above is for *crosstalk between people*, and cannot be asked to also
arbitrate between one person's own mics.
"""
from typing import Dict, List, Optional, Tuple

from caption_engine.transcriber.word import Word

from . import energy as energy_mod
from .transcript import Utterance, build_utterances

# A word is often ~0.2s; scoring a window that short is noisy, so widen it.
MIN_SCORE_WINDOW = 0.25
DEFAULT_MARGIN = 12
DEFAULT_KEEP_RATIO = 0.5


def own_word_fraction(speaker: str, words: List[Word],
                      envelopes: Dict[str, dict],
                      margin: int = DEFAULT_MARGIN) -> float:
    """Fraction of ``words`` where ``speaker``'s own mic was the loudest.

    1.0 means every word was this speaker's; near 0 means the whole run is bleed
    from someone else's voice. ``envelopes`` must be keyed by speaker — see the
    module docstring for why per-camera keys break this.
    """
    if not words:
        return 0.0
    if speaker not in envelopes:
        # Nothing to compare against — trust the transcript rather than drop it.
        return 1.0

    wins = 0
    for w in words:
        start, end = _padded(w)
        scores = energy_mod.speaker_scores(envelopes, start, end)
        if not scores:
            wins += 1          # silence everywhere; no evidence of bleed
            continue
        top = max(scores.values())
        if scores.get(speaker, 0) >= top - margin:
            wins += 1
    return wins / len(words)


def _padded(w: Word) -> Tuple[float, float]:
    start = float(w.start or 0.0)
    end = float(w.end if w.end is not None else start)
    if end - start < MIN_SCORE_WINDOW:
        mid = (start + end) / 2.0
        start, end = mid - MIN_SCORE_WINDOW / 2, mid + MIN_SCORE_WINDOW / 2
    return max(0.0, start), max(0.0, end)


def merge_per_mic(per_speaker_words: Dict[str, List[Word]],
                  envelopes: Dict[str, dict],
                  margin: int = DEFAULT_MARGIN,
                  keep_ratio: float = DEFAULT_KEEP_RATIO,
                  ) -> Tuple[List[Utterance], dict]:
    """Merge one transcript per speaker into a single speaker-labelled timeline.

    Both dicts are keyed by speaker id — one entry per *person*, however many
    cameras they own. Two entries for one person is the caller's bug, and shows
    up as every line of theirs appearing twice.

    Returns ``(utterances, report)``. The report is what the agent shows the
    user: how much of each speaker's transcript survived, so a mic that was
    mostly bleed (or a bad ``margin``) is visible rather than silently swallowed.
    """
    kept: List[Utterance] = []
    report: Dict[str, dict] = {}

    for speaker in sorted(per_speaker_words):
        words = per_speaker_words[speaker] or []
        utterances = build_utterances(words)
        n_kept = 0
        for u in utterances:
            # build_utterances keeps the Word objects; without them there is no
            # per-word evidence and the utterance can only be taken on trust.
            share = own_word_fraction(speaker, u.words, envelopes, margin)
            if share >= keep_ratio:
                u.speaker = speaker
                u.speaker_confidence = round(share, 3)
                kept.append(u)
                n_kept += 1
        report[speaker] = {
            "utterances": len(utterances),
            "kept": n_kept,
            "dropped_as_bleed": len(utterances) - n_kept,
            "words": len(words),
        }

    kept.sort(key=lambda u: (u.start, u.speaker or ""))
    for i, u in enumerate(kept):
        u.index = i

    report["_totals"] = {
        "speakers": sorted(per_speaker_words),
        "utterances": len(kept),
        "overlaps": _count_overlaps(kept),
    }
    return kept, report


def _count_overlaps(utterances: List[Utterance]) -> int:
    """Utterances that run over the start of a different speaker's next one.

    Reported because it's the payoff of per-mic transcription: with a single mix
    this number can only ever be 0.
    """
    n = 0
    for a, b in zip(utterances, utterances[1:]):
        if a.speaker != b.speaker and a.end > b.start + 1e-6:
            n += 1
    return n


def merged_words(utterances: List[Utterance]) -> List[Word]:
    """Flatten a merged timeline back to a word list for captioning.

    Words are re-sorted by time across speakers, so a clip that spans a handover
    captions in the order it is heard.
    """
    words = [w for u in utterances for w in (u.words or [])]
    words.sort(key=lambda w: (w.start if w.start is not None else 0.0,
                              w.end if w.end is not None else 0.0))
    return words
