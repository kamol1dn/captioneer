from skleyka.transcript import group_utterances, map_words, to_file_time, voice_candidates


def word(text, start, end):
    return {"text": text, "src_start": start, "src_end": end}


CLIPS = [
    {"start": 0.0, "end": 10.0, "in": 100.0, "out": 110.0},
    {"start": 10.0, "end": 15.0, "in": 120.0, "out": 125.0},   # 110-120 of the file was cut out
    {"start": 20.0, "end": 25.0, "in": 100.0, "out": 105.0},   # the opening reused later
]


def test_words_follow_the_cut():
    words = [word("a", 101.0, 101.5), word("b", 109.8, 110.4), word("c", 115.0, 115.5), word("d", 121.0, 121.5)]
    mapped = map_words(words, CLIPS)
    texts = [(w["text"], w["start"], w["end"]) for w in mapped]
    assert ("a", 1.0, 1.5) in texts
    assert ("a", 21.0, 21.5) in texts          # reused material: the word appears twice
    assert ("b", 9.8, 10.0) in texts           # cut by the edit: clipped to the clip's end
    assert all(t[0] != "c" for t in texts)     # in the removed stretch
    assert ("d", 11.0, 11.5) in texts


def test_file_time_lookup():
    assert to_file_time(CLIPS, 12.0) == 122.0
    assert to_file_time(CLIPS, 17.0) is None


def test_utterances_break_on_speaker_gap_and_length():
    words = [
        {"text": "salom", "start": 0.0, "end": 0.4, "spk": "A"},
        {"text": "dunyo", "start": 0.5, "end": 0.9, "spk": "A"},
        {"text": "ha", "start": 1.0, "end": 1.2, "spk": "B"},       # speaker change
        {"text": "yaxshi", "start": 3.0, "end": 3.4, "spk": "B"},   # gap > 0.8 s
    ] + [{"text": "x", "start": 4 + i * 0.5, "end": 4.3 + i * 0.5, "spk": "B"} for i in range(40)]
    utts = group_utterances(words)
    assert [u["text"] for u in utts[:2]] == ["salom dunyo", "ha"]
    assert utts[2]["text"].startswith("yaxshi x")       # 0.6 s gap: same line
    assert all(u["end"] - u["start"] <= 15.0 for u in utts)
    assert len(utts) >= 4                                  # the long run was split


def test_voice_candidates_prefer_the_mix():
    tl = {"audio": [
        {"index": 0, "muted": False, "clips": [{"start": 0, "end": 100, "media_path": r"D:\ep\Audio\Live-Mix.wav"}]},
        {"index": 1, "muted": False, "clips": [{"start": 0, "end": 100, "media_path": r"D:\ep\Video\CAM1.mp4"}]},
        {"index": 2, "muted": True, "clips": [{"start": 0, "end": 100, "media_path": r"D:\ep\Audio\MIC1.wav"}]},
        {"index": 3, "muted": False, "clips": [{"start": 0, "end": 10, "media_path": r"D:\sfx\whoosh.wav"},
                                                {"start": 50, "end": 60, "media_path": r"D:\sfx\boom.wav"}]},
    ]}
    c = voice_candidates(tl)
    assert [x["label"] for x in c] == ["A1", "A2"]
    assert c[0]["mix_name"] and c[0]["audio_only"]
