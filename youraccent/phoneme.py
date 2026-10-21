"""A judge that listens for sounds instead of words.

The model (facebook/wav2vec2-xlsr-53-espeak-cv-ft, the most downloaded phoneme recognizer on Hugging Face)
writes down the sounds it hears (IPA symbols, about one every 20 ms) without a word model to fix them up.
Whisper turns a slightly wrong "right" into "right" by itself; this model keeps the L it heard.

The sentence's expected sounds come from espeak, word by word. Both sequences are lined up (edit distance),
and each written word is marked:
    ok      the sounds are as expected
    doubt   only a vowel differs, a sound is missing, or the model was not sure (it is often unsure)
    wrong   a consonant came out as another consonant (R as L, th as s ...)
    missed  none of the word's sounds were heard
Small function words (the, a, in ...) are never marked wrong.
"""

import re

from youraccent.judge import SKIP_DOUBT, norm

MODEL = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"
FRAME = 0.02  # seconds per model output frame
SURE = 0.5  # a swapped consonant counts as wrong only if the model was at least this sure of what it heard
CONSONANTS = set("p b t d k g f v θ ð s z ʃ ʒ h tʃ dʒ m n ŋ l ɹ r w j ɾ ʔ".split())

# Plain-Korean explanations of the swaps Korean speakers make most often: (expected, heard)
SWAPS = {
    ("l", "ɹ"): "L이 R처럼 들렸어요", ("ɹ", "l"): "R이 L처럼 들렸어요",
    ("θ", "s"): "th가 s처럼 들렸어요", ("θ", "t"): "th가 t처럼 들렸어요", ("θ", "f"): "th가 f처럼 들렸어요",
    ("θ", "ð"): "th가 울리는 소리(ð)로 들렸어요", ("ð", "d"): "th(ð)가 d처럼 들렸어요", ("ð", "z"): "th(ð)가 z처럼 들렸어요",
    ("ð", "θ"): "th(ð)가 울리지 않는 소리(θ)로 들렸어요",
    ("v", "b"): "V가 B처럼 들렸어요", ("b", "v"): "B가 V처럼 들렸어요", ("v", "w"): "V가 W처럼 들렸어요", ("w", "v"): "W가 V처럼 들렸어요",
    ("f", "p"): "F가 P처럼 들렸어요", ("p", "f"): "P가 F처럼 들렸어요",
    ("z", "s"): "Z가 S처럼 들렸어요", ("s", "z"): "S가 Z처럼 들렸어요", ("ʃ", "s"): "sh가 s처럼 들렸어요", ("s", "ʃ"): "s가 sh처럼 들렸어요",
    ("dʒ", "tʃ"): "j가 ch처럼 들렸어요", ("tʃ", "dʒ"): "ch가 j처럼 들렸어요",
}


def canon(p):
    """Spellings of the same sound are treated as equal when comparing."""
    p = p.replace("ː", "")
    return {"ɚ": "ə", "ɜ": "ə", "ɐ": "ə", "ᵻ": "ɪ", "r": "ɹ", "ɕ": "ʃ", "ʑ": "ʒ"}.get(p, p)


def equivalent(a, b):
    a, b = canon(a), canon(b)
    return a == b or (a == "ɾ" and b in ("t", "d")) or (b == "ɾ" and a in ("t", "d"))  # the American flap


# The model often mixes up voiced and unvoiced fricatives at the start of a word (sink heard as zink,
# ship as zhip). That is its weakness, not a typical mistake of Korean speakers, so such a swap is only "doubt".
VOICING = [{"s", "z"}, {"ʃ", "ʒ"}, {"θ", "ð"}, {"tʃ", "dʒ"}]


FINAL_VOICING = [{"p", "b"}, {"t", "d"}, {"k", "g"}]  # at the end of a word the voicing of a stop is hard to hear


def voicing_only(a, b, final=False):
    a, b = canon(a), canon(b)
    return any(a in group and b in group for group in VOICING + (FINAL_VOICING if final else []))


def is_consonant(p):
    return canon(p) in CONSONANTS


def align_sounds(expected, heard):
    """Edit-distance alignment. Returns a list of (expected index or None, heard index or None)."""
    n, m = len(expected), len(heard)

    def sub(a, b):
        if equivalent(a, b):
            return 0.0
        return 0.6 if is_consonant(a) == is_consonant(b) else 1.0

    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i
    for j in range(1, m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(cost[i - 1][j - 1] + sub(expected[i - 1], heard[j - 1]), cost[i - 1][j] + 1, cost[i][j - 1] + 1)
    pairs, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(cost[i][j] - (cost[i - 1][j - 1] + sub(expected[i - 1], heard[j - 1]))) < 1e-9:
            pairs.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and abs(cost[i][j] - (cost[i - 1][j] + 1)) < 1e-9:
            pairs.append((i - 1, None)); i -= 1
        else:
            pairs.append((None, j - 1)); j -= 1
    return pairs[::-1]


def judge_words(words, expected_per_word, heard, doubt_below=SURE):
    """Marks each word. `words`: the written words. `expected_per_word`: a list of sounds for each word.
    `heard`: a list of dicts {sound, prob, start, end}. Returns the rows, one per word."""
    exp, owner = [], []
    for w, sounds in enumerate(expected_per_word):
        exp += sounds
        owner += [w] * len(sounds)
    pairs = align_sounds(exp, [h["sound"] for h in heard])
    per_word = [{"heard": [], "swaps": [], "lost": [], "matched": 0, "extra": 0} for _ in words]
    last_word = 0
    for i, j in pairs:
        if i is not None:
            last_word = owner[i]
        w = owner[i] if i is not None else last_word  # a sound heard with no partner joins the word before it
        entry = per_word[w]
        if j is not None:
            entry["heard"].append(heard[j])
        if i is not None and j is not None:
            if equivalent(exp[i], heard[j]["sound"]):
                entry["matched"] += 1
            else:
                last_of_word = i + 1 >= len(exp) or owner[i + 1] != owner[i]
                entry["swaps"].append((exp[i], heard[j]["sound"], heard[j]["prob"], last_of_word))
        elif i is not None:
            entry["lost"].append(exp[i])
        else:
            entry["extra"] += 1
    rows = []
    for w, word in enumerate(words):
        e = per_word[w]
        sounds = expected_per_word[w]
        heard_here = e["heard"]
        if not sounds:
            status = "ok"
        elif not heard_here:
            status = "missed"
        else:
            hard = [s for s in e["swaps"] if is_consonant(s[0]) and is_consonant(s[1]) and s[2] >= doubt_below
                    and not voicing_only(s[0], s[1], s[3])]
            problems = bool(e["swaps"] or e["lost"] or e["extra"])
            status = "wrong" if hard else ("doubt" if problems else "ok")
            if word.lower() in SKIP_DOUBT and status == "wrong":
                status = "doubt"  # small function words are said fast and often misheard
        notes = [("울림(유성/무성)이 조금 달랐을 수 있어요" if voicing_only(a, b, fin) else SWAPS.get((canon(a), canon(b))) or f"{a} 소리가 {b}로 들렸어요")
                 for a, b, _, fin in e["swaps"] if is_consonant(a) and is_consonant(b)]
        notes += [f"{p} 소리가 빠진 것 같아요" for p in e["lost"] if is_consonant(p)]
        rows.append({
            "word": word,
            "status": status,
            "heard_as": " ".join(h["sound"] for h in heard_here),
            "expected": " ".join(sounds),
            "note": " · ".join(notes),
            "prob": round(sum(h["prob"] for h in heard_here) / len(heard_here), 2) if heard_here else 0.0,
            "start": min((h["start"] for h in heard_here), default=None),
            "end": max((h["end"] for h in heard_here), default=None),
        })
    return rows


class PhonemeJudge:
    name = "phoneme"

    def __init__(self):
        self.model = None
        self.processor = None
        self.device = "cpu"
        self.cache = {}

    def _load(self):
        import espeakng_loader
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
        import torch

        self.processor = Wav2Vec2Processor.from_pretrained(MODEL)
        self.model = Wav2Vec2ForCTC.from_pretrained(MODEL).eval()
        # The Mac's GPU runs it in about 0.2 s (the CPU took 6 s on a busy Mac) with the same answer.
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        if self.device == "mps":  # half the memory (0.63 GB instead of 1.26 GB), the same answer in the tests
            self.model.half()
        self.model.to(self.device)

    def warmup(self):
        """Load the model and run it once, so the first real reading is not slow."""
        import numpy as np

        if self.model is None:
            self._load()
        for _ in range(2):  # the first run on the GPU is slow (it sets itself up)
            self.recognize(np.zeros(16000, dtype=np.float32))
        self.expected("warm")

    def expected(self, word):
        key = re.sub(r"[^A-Za-z']", "", word).lower()
        if not key:
            return []
        if key not in self.cache:
            text = self.processor.tokenizer.phonemize(key, "en-us")
            self.cache[key] = [p for p in text.split() if p != "|"]
        return self.cache[key]

    def recognize(self, audio):
        """The sounds heard: a list of {sound, prob, start, end} (seconds)."""
        import torch

        inputs = self.processor(audio, sampling_rate=16000, return_tensors="pt")
        try:
            with torch.no_grad():
                values = inputs.input_values.to(self.device)
                if self.device == "mps":
                    values = values.half()
                probs = torch.softmax(self.model(values).logits[0].float(), dim=-1).cpu()
        except RuntimeError:  # the GPU could not do it: fall back to the CPU for good
            self.device = "cpu"
            self.model.float().to("cpu")
            with torch.no_grad():
                probs = torch.softmax(self.model(inputs.input_values).logits[0], dim=-1)
        best, ids = probs.max(dim=-1)
        tokenizer = self.processor.tokenizer
        specials = set(tokenizer.all_special_ids)
        heard, run_start = [], 0
        ids, best = ids.tolist(), best.tolist()
        for k in range(len(ids) + 1):
            if k == len(ids) or ids[k] != ids[run_start]:
                if ids[run_start] not in specials and not re.search(r"\d", tokenizer.convert_ids_to_tokens(ids[run_start])):
                    run = best[run_start:k]
                    heard.append({"sound": tokenizer.convert_ids_to_tokens(ids[run_start]), "prob": max(run),
                                  "start": run_start * FRAME, "end": k * FRAME})
                run_start = k
        return heard

    def judge(self, audio, text):
        if self.model is None:
            self._load()
        words = [w.strip(".,?!;:\"()") for w in text.split() if norm(w)]
        heard = self.recognize(audio)
        rows = judge_words(words, [self.expected(w) for w in words], heard)
        return {"engine": self.name, "heard": " ".join(h["sound"] for h in heard), "rows": rows, "extra": []}
