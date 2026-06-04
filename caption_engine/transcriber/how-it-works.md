# How word-level timing works (forced alignment)

> "How is it even possible to align *each word*?"

The trick is that **we are not recognizing the words** — Kotib (Whisper) already
did that. We already have the exact transcript. The only question left is:

> Given the audio **and** the known text, *where in time* does each word sit?

That is **forced alignment**, and it's a much easier, *exactly solvable* problem
than recognition. This doc explains it visually, then maps every step to the code
in this folder.

---

## 0. The mental model in one picture

```
   audio.wav ──► [Kotib / Whisper] ──► "salom dunyo"      (WHAT was said)
                                            │
                                            ▼
   audio.wav ──► [MMS wav2vec2]  ──►  emission matrix      (per-frame letter probs)
                                            │
              "salom dunyo" ──────────────► │  forced alignment (Viterbi)
                                            ▼
                       salom: 0.02s → 0.36s    dunyo: 0.42s → 0.95s   (WHEN)
```

Two different models, two different jobs:
- **Kotib** answers *what* (great text, jittery timing — we throw its timing away).
- **MMS** answers *when* (we feed it the known text and it pins it to the audio).

---

## 1. Audio becomes a stack of tiny frames

The wav2vec2 model doesn't look at the waveform sample-by-sample. It chops the
16 kHz audio into short **frames** of about **20 ms** each (≈ 50 frames per
second):

```
 waveform:  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~  (16000 samples/sec)
 frames:    | f0 | f1 | f2 | f3 | f4 | f5 | ... |              (~20 ms each)
            0    20   40   60   80  100  120  ms
```

Everything downstream works in **frame units**; we only convert to seconds at the
very end.

---

## 2. The emission matrix — the model's actual output

For **each frame**, the model outputs a probability for **each letter** in its
small alphabet (`a b c … z` + apostrophe), plus two special tokens:

- `⎵`  the **blank** ("no new letter here" — silence, or a held sound)
- `*`  the **star** (a sound that isn't in the alphabet; we avoid relying on it)

So the output is a grid — **letters down the side, time across the top** — where
each column is one frame's probability distribution. Here's the argmax (the
winning letter) per frame for the word *salom*:

```
            frames →
        f0  f1  f2  f3  f4  f5  f6  f7  f8  f9 f10 f11 f12 f13 f14 f15 f16 f17 f18
  ⎵     ██                                                                  ██  ██
  s         ██  ██  ██
  a                     ██  ██  ██  ██
  l                                     ██  ██  ██
  o                                                 ██  ██  ██  ██
  m                                                                 ██  ██  ██
  (rest of alphabet: low probability everywhere)
```

Read it left to right, taking the loudest letter each frame:

```
⎵ s s s a a a a l l l o o o o m m m ⎵
```

This is the raw, frame-by-frame "spelling" the acoustic model hears.

---

## 3. CTC: why one letter spans many frames

Speech is slower than 20 ms, so a single spoken letter naturally lights up for
**several frames in a row**. CTC (Connectionist Temporal Classification) defines
how to read that back into clean text with two rules:

1. **Merge repeats:**  `s s s → s`,  `a a a a → a`
2. **Then drop blanks:**  remove every `⎵`

```
  ⎵ s s s a a a a l l l o o o o m m m ⎵
        └─merge repeats─┘
  ⎵ s a l o m ⎵
        └─drop blanks─┘
  s a l o m            ✅  "salom"
```

(The blank also lets you write real double letters: `k e t ⎵ t i` collapses to
`ketti`, not `keti` — the blank keeps the two `t`s apart.)

**The point:** that "letter held for N frames" is exactly the timing information
we want. `s` occupied frames 1–3, `o` occupied frames 11–14, and so on.

---

## 4. Forced alignment: walk the *known* word through the grid

Free decoding would let the model pick any letters (that's recognition, and it
can guess wrong). **Forced** alignment fixes the answer: we *require* the path to
spell exactly `s a l o m`, in order. The model only gets to decide **how many
frames** each letter (and each blank) takes.

Think of it as a track the path must follow top-to-bottom, while moving
left-to-right through time. At every frame it may **stay** on the current letter
(hold it), or **advance** to the next one — never skip, never reorder:

```
              frames →
            f0 f1 f2 f3 f4 f5 f6 f7 f8 f9 f10 f11 f12 f13 f14 f15 f16 f17 f18
   ⎵        ●
   s        └─►●──●──●
   a                  └─►●──●──●──●
   l                              └─►●──●──●
   o                                       └─►●──●──●──●
   m                                                   └─►●──●──●
                                                              (end)
```

Among the astronomically many ways to stretch `salom` across these frames, the
**Viterbi algorithm** finds the single path with the **highest total
probability** under the emission matrix — efficiently, with dynamic programming.
Because the letters are locked in, the answer is unambiguous: the best path *is*
the alignment.

---

## 5. From the path to timestamps

The winning path hands us a **frame span for every letter**, which we collapse
into a **span per word** (first letter's start → last letter's end):

```
  letter:   s      a        l       o         m
  frames:  1–3    4–7      8–10    11–14     15–17
                                                     word "salom" → frames 1 … 17
```

Then convert frames → seconds with one ratio:

```
  seconds_per_frame = total_samples / number_of_frames / 16000

  salom.start = 1  × seconds_per_frame ≈ 0.02 s
  salom.end   = 17 × seconds_per_frame ≈ 0.36 s
```

Done — every word now has a start and end pinned to the actual audio.

---

## 6. The Uzbek wrinkle: romanization

The MMS alphabet is ~26 Latin letters + apostrophe. Uzbek uses `oʻ`, `gʻ`, the
`ʻ` mark, and Russian loanwords. So before alignment we **romanize each word**
down to that alphabet with `uroman`:

```
  oʻzbek   ──uroman──►  o'zbek    (apostrophe is in the alphabet ✓)
  gʻalaba  ──uroman──►  g'alaba
  yaxshi   ──uroman──►  yaxshi
  salom!   ──uroman──►  salom     (punctuation stripped)
```

We align the **romanized** spelling, but keep the **original** word for display.
The timing belongs to the sound, so it transfers back unchanged.

---

## 7. Words with no letters (digits, symbols)

Some "words" romanize to **nothing** — `"123"`, a lone `"—"`. They have no sound
the letter-aligner can grab onto, so they get **no anchor**. Instead of guessing,
we **interpolate**: spread them evenly across the time between their aligned
neighbours, keeping everything monotonic.

```
  "salom"   [0.02 – 0.36]   ← aligned
  "123"     [0.36 – 0.40]   ← no letters: interpolated into the gap
  "dunyo"   [0.40 – 0.95]   ← aligned
```

---

## 8. How this maps to the code

| Step (above)                         | Where it lives                                   |
|--------------------------------------|--------------------------------------------------|
| Decode audio → 16 kHz mono           | [`audio.py`](audio.py) → `load_audio()`          |
| Get the transcript (the *what*)      | [`kotib_backend.py`](kotib_backend.py) → `transcribe_kotib()` |
| Split transcript into words          | `kotib_backend.py` → `_WORD_RE.findall(text)`    |
| Romanize each word (§6)              | [`mms_align.py`](mms_align.py) → `_normalize()`  |
| Audio → **emission matrix** (§2)     | `mms_align.py` → `model(waveform)`               |
| **Forced alignment / Viterbi** (§4)  | `mms_align.py` → `aligner(emission, tokenizer(words))` |
| Letter spans → word spans (§5)       | `mms_align.py` → the `token_spans` loop          |
| Frames → seconds (§5)                | `mms_align.py` → `sec_per_frame`                 |
| Interpolate letterless words (§7)    | `mms_align.py` → `_interpolate()`                |
| Build the final `Word` list          | `kotib_backend.py` → returns `[Word(...)]`       |

Reading `align_words()` in [`mms_align.py`](mms_align.py) top-to-bottom now follows
this exact order: normalize → keep alignable words → emission → align → span→seconds
→ interpolate.

---

## 9. Why this beats Whisper's own word timestamps

Whisper *can* emit word timings, but it infers them indirectly from its internal
cross-attention — which drifts ±100–300 ms and isn't consistent. Forced alignment
reads timing **straight from a frame-by-frame acoustic model constrained to the
known text**, so it lands at roughly **±20–50 ms**. That's why WhisperX exists for
English, and why we use MMS the same way for Uzbek: *let one model say the words,
let a second model say exactly when.*
```
  Whisper timestamps:   ~~~ guessed from attention ~~~     (±100–300 ms, wobbly)
  Forced alignment:     ── measured against the audio ──   (±20–50 ms, tight)
```
