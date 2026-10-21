"""Judging a sentence Jun read aloud: which words came out as written?

Today the judge is Whisper (it writes down the words it heard, with how sure it was about each).
Whisper tends to correct a mispronounced word into the likely one, so it can miss real errors;
that is why the judge is a separate piece: a model that writes down sounds instead of words can
take its place later. A judge is any object with  judge(audio16k, expected_text) -> dict.

Each word of the written sentence gets a status:
    ok      heard as written, and Whisper was sure
    doubt   heard as written, but Whisper was not sure
    wrong   heard as a different word
    missed  not heard
"""

import re
from difflib import SequenceMatcher

MODELS = {
    "small": "mlx-community/whisper-small-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}
MAX_TOKENS = 160
DOUBT = 0.6
# Short function words and the first word of a recording often get a low score for reasons that
# have nothing to do with the sound, so they are never marked "doubt".
SKIP_DOUBT = {"the", "a", "an", "of", "to", "and", "is", "are", "on", "in", "i", "it", "at", "or"}


def norm(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def align(expected, heard, doubt=DOUBT):
    """Line up the written sentence with the heard words.

    `heard` is a list of dicts: word, prob, start, end (seconds; may be None).
    Returns (rows, extra): one row (a dict) per written word, and the heard words that are not in
    the sentence.
    """
    shown = [w.strip(".,?!;:\"()") for w in expected.split() if norm(w)]
    want = [norm(w) for w in shown]
    got = [dict(h, key=norm(h["word"])) for h in heard if norm(h["word"])]
    rows = [None] * len(want)
    extra = []

    def row(i, status, block):
        rows[i] = {
            "word": shown[i],
            "status": status,
            "heard_as": " ".join(g["key"] for g in block),
            "prob": min((g["prob"] for g in block), default=0.0),
            "start": block[0].get("start") if block else None,
            "end": block[-1].get("end") if block else None,
        }

    matcher = SequenceMatcher(None, want, [g["key"] for g in got], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                i, g = i1 + k, got[j1 + k]
                unsure = g["prob"] < doubt and i > 0 and want[i] not in SKIP_DOUBT
                row(i, "doubt" if unsure else "ok", [g])
        elif tag == "replace":
            for k, i in enumerate(range(i1, i2)):
                same_size = i2 - i1 == j2 - j1
                row(i, "wrong", [got[j1 + k]] if same_size else got[j1:j2])
        elif tag == "delete":
            for i in range(i1, i2):
                row(i, "missed", [])
        else:  # insert: heard, but not in the sentence
            extra.extend(got[j1:j2])
    return rows, extra


def compare(expected, heard, doubt=DOUBT):
    """The older tuple form used by the command-line test: heard is [(word, probability)]."""
    rows, extra = align(expected, [{"word": w, "prob": p, "start": None, "end": None} for w, p in heard], doubt)
    return [(r["word"], r["status"], r["heard_as"], r["prob"]) for r in rows], [(e["word"], e["prob"]) for e in extra]


def transcribe_words(audio, model="small"):
    """Whisper's text and its words with probability and time (audio: 16 kHz mono float32)."""
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=MODELS[model],
        language="en",
        condition_on_previous_text=False,  # and no prompt with the script: that would hide errors
        temperature=0.0,
        sample_len=MAX_TOKENS,
        word_timestamps=True,
    )
    words = [
        {"word": w["word"], "prob": w["probability"], "start": w["start"], "end": w["end"]}
        for s in result["segments"]
        for w in s.get("words", [])
    ]
    return result["text"].strip(), words


def listen(audio, model="small", doubt=DOUBT):
    """The older form used by the command-line test: (text, [(word, probability)])."""
    text, words = transcribe_words(audio, model)
    return text, [(w["word"], w["prob"]) for w in words]


class WhisperJudge:
    name = "whisper"

    def __init__(self, model="small", doubt=DOUBT):
        self.model = model
        self.doubt = doubt

    def judge(self, audio, expected, accent=None):  # (the accent only matters for the sound judge)
        text, words = transcribe_words(audio, self.model)
        rows, extra = align(expected, words, self.doubt)
        return {"engine": self.name, "heard": text, "rows": rows, "extra": [e["word"] for e in extra]}
