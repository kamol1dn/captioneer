"""Long-form subtitle generation built on top of `caption_engine`.

This package adds a memory-bounded path for turning hour-long media into a
plain subtitle file (.srt / .vtt). It reuses the existing transcription engine
(Kotib + MMS forced alignment for Uzbek, WhisperX / faster-whisper otherwise)
without modifying it — see `subtitle_gen`.
"""
