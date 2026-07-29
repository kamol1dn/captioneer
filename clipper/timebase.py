"""Seconds <-> frames, and the NTSC mess.

xmeml has no concept of seconds. Every position is an integer frame count, and
the sequence declares an *integer* timebase plus an `ntsc` flag — never a
fractional rate:

    real fps   <timebase>   <ntsc>
    23.976        24         TRUE
    24            24         FALSE
    25            25         FALSE
    29.97         30         TRUE
    30            30         FALSE
    59.94         60         TRUE

The trap: 29.97 footage is *not* 30 fps. Converting seconds to frames at 30
instead of 30000/1001 drifts ~2 frames per minute — an hour-long episode ends
up ~2 seconds off, and cuts near the end of a clip land visibly late. So the
exact rate stays a Fraction everywhere and only becomes an integer at the last
possible moment.
"""
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

# Rates where the integer timebase is a rounded-up NTSC rate.
_NTSC_RATES = {
    Fraction(24000, 1001): 24,
    Fraction(30000, 1001): 30,
    Fraction(60000, 1001): 60,
    Fraction(48000, 1001): 48,
}


@dataclass(frozen=True)
class Timebase:
    """A sequence's frame rate in the form xmeml wants it."""
    timebase: int          # integer frames per second as declared in XML
    ntsc: bool = False     # True => real rate is timebase * 1000/1001
    drop_frame: bool = False

    @property
    def fps(self) -> Fraction:
        """The *exact* rate. Use this for all arithmetic."""
        if self.ntsc:
            return Fraction(self.timebase * 1000, 1001)
        return Fraction(self.timebase)

    def to_frames(self, seconds: float) -> int:
        """Round a time in seconds to the nearest whole frame.

        Round-half-up via floor(x + 1/2) on exact rationals — Python's round()
        does banker's rounding, which makes boundaries land inconsistently.
        """
        if seconds <= 0:
            return 0
        exact = Fraction(seconds).limit_denominator(1_000_000) * self.fps
        return int((exact + Fraction(1, 2)).__floor__())

    def to_seconds(self, frames: int) -> float:
        return float(Fraction(frames) / self.fps)

    def to_timecode(self, frames: int) -> str:
        """HH:MM:SS:FF (non-drop) or HH:MM:SS;FF (drop-frame).

        Drop-frame only renumbers the *labels*; it never changes how many frames
        exist. So this affects display strings and nothing in the edit math.
        """
        tb = self.timebase
        f = int(frames)
        if self.drop_frame and tb in (30, 60):
            f = _to_dropframe_number(f, tb)
        hh, rem = divmod(f, tb * 3600)
        mm, rem = divmod(rem, tb * 60)
        ss, ff = divmod(rem, tb)
        sep = ";" if self.drop_frame else ":"
        return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"

    def from_timecode(self, tc: str) -> int:
        """Parse HH:MM:SS:FF / HH:MM:SS;FF back to a frame count."""
        parts = tc.replace(";", ":").split(":")
        if len(parts) != 4:
            raise ValueError(f"not a timecode: {tc!r}")
        hh, mm, ss, ff = (int(p) for p in parts)
        n = ((hh * 60 + mm) * 60 + ss) * self.timebase + ff
        if self.drop_frame and self.timebase in (30, 60):
            n -= _dropped_before(hh, mm, self.timebase)
        return n

    def to_dict(self) -> dict:
        return {"timebase": self.timebase, "ntsc": self.ntsc,
                "drop_frame": self.drop_frame}

    @classmethod
    def from_dict(cls, d: dict) -> "Timebase":
        return cls(timebase=int(d["timebase"]),
                   ntsc=bool(d.get("ntsc", False)),
                   drop_frame=bool(d.get("drop_frame", False)))

    @classmethod
    def from_fps(cls, fps: Optional[Fraction], drop_frame: bool = False) -> "Timebase":
        """Build a Timebase from ffprobe's exact r_frame_rate.

        Falls back to 30 non-NTSC when the rate is missing (audio-only source).
        """
        if fps is None:
            return cls(timebase=30, ntsc=False, drop_frame=drop_frame)
        fps = Fraction(fps)
        if fps in _NTSC_RATES:
            return cls(timebase=_NTSC_RATES[fps], ntsc=True, drop_frame=drop_frame)
        if fps.denominator == 1:
            return cls(timebase=int(fps), ntsc=False, drop_frame=drop_frame)
        # Odd rate (e.g. a variable-frame-rate phone export probed as 90000/3001).
        # Snap to the nearest known NTSC rate if it's within a frame, else round.
        for exact, tb in _NTSC_RATES.items():
            if abs(fps - exact) < Fraction(1, 100):
                return cls(timebase=tb, ntsc=True, drop_frame=drop_frame)
        return cls(timebase=int(round(float(fps))), ntsc=False,
                   drop_frame=drop_frame)

    def __str__(self) -> str:
        return f"{float(self.fps):.3f}fps (timebase {self.timebase}" \
               f"{', ntsc' if self.ntsc else ''}{', df' if self.drop_frame else ''})"


def _to_dropframe_number(frame: int, tb: int) -> int:
    """Convert a real frame index to its drop-frame label number."""
    drop = 2 * (tb // 30)          # 2 per minute at 30, 4 at 60
    per_min = tb * 60
    per_10min = per_min * 10 - drop * 9
    tens, rem = divmod(frame, per_10min)
    if rem < drop:
        return frame + drop * 9 * tens
    mins, _ = divmod(rem - drop, per_min - drop)
    return frame + drop * (9 * tens + mins)


def _dropped_before(hours: int, minutes: int, tb: int) -> int:
    """How many frame numbers are skipped before HH:MM in drop-frame."""
    drop = 2 * (tb // 30)
    total_min = hours * 60 + minutes
    return drop * (total_min - total_min // 10)
