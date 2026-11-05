"""Streaming test, engine A: Whisper (MLX) + LocalAgreement-2.

Plays an audio file into the engine at real-time speed, as if it were a live meeting,
and records when each word first appears (grey, may still change) and when it is confirmed.

    .venv/bin/python bench/stream_whisper.py AUDIO [--ref REF.txt] [--model small|turbo]
                                               [--step 0.7] [--out bench/results]

How it works: the sound of the current utterance is kept in a buffer and Whisper is run on the
whole buffer every --step seconds (or as soon as the last run finished, if that took longer).
A word that came out the same in two runs in a row is confirmed (LocalAgreement-2, as in
whisper_streaming). When every word of a Whisper segment (roughly a sentence) is confirmed and a
newer segment follows, the buffer is cut at that segment's end, so no word is ever split between
two buffers; the buffer never grows past --max-buffer seconds.

Word timestamps (--word-ts) cost 1-2.5 s extra per call on an 8 GB M1, so by default each word's
time is estimated inside its segment by character position (used only for the delay numbers).

Output (same format as the Swift engine, read by bench/score.py):
    <out>/<name>.whisper-<model>.jsonl   one line per confirmed word:
        {"word", "audio_start", "audio_end", "shown", "confirmed"}   (seconds; shown/confirmed
        are wall-clock seconds since the audio started playing)
    plus a "meta" first line with calls, compute time, CPU time and peak memory.
"""

import argparse
import json
import os
import re
import resource
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np

RATE = 16000
MODELS = {
    "small": "mlx-community/whisper-small-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}
SENTENCE_END = re.compile(r"[.?!]$")


def load_audio(path):
    """Any file macOS can read -> mono float32 at 16 kHz (afconvert ships with macOS; no ffmpeg)."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "a.wav")
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", path, wav],
                       check=True)
        with wave.open(wav) as w:
            data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def norm(word):
    return re.sub(r"[^\w']", "", word.lower())


class Streamer:
    def __init__(self, model, step, max_buffer, word_ts=False):
        import mlx_whisper  # imported here so --help is instant

        self.mlx_whisper = mlx_whisper
        self.model = model
        self.step = step
        self.max_buffer = max_buffer
        self.word_ts = word_ts
        self.buffer_start = 0.0  # audio time where the buffer begins
        self.committed = []  # confirmed words: dicts with word/audio_start/audio_end/shown/confirmed
        self.previous = []  # tail of the previous run: [(word, start, end)]
        self.first_seen = []  # wall time each word of the current tail was first shown unchanged
        self.calls = 0
        self.compute = 0.0

    def _run(self, audio):
        prompt = " ".join(w["word"] for w in self.committed[-40:]) or None
        t0 = time.monotonic()
        result = self.mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.model,
            language="en",
            condition_on_previous_text=False,
            initial_prompt=prompt,
            temperature=0.0,
            word_timestamps=self.word_ts,
        )
        self.compute += time.monotonic() - t0
        self.calls += 1
        # (text, start, end, segment_end or None): segment_end is set on the last word of every
        # segment except the final one, i.e. where the buffer may safely be cut.
        words = []
        segments = result["segments"]
        b = self.buffer_start
        for si, seg in enumerate(segments):
            if self.word_ts:
                items = [(w["word"].strip(), b + w["start"], b + w["end"]) for w in seg.get("words", [])]
            else:
                toks = seg["text"].split()
                total = sum(len(t) + 1 for t in toks) or 1
                s0, s1, pos, items = b + seg["start"], b + seg["end"], 0, []
                for t in toks:
                    a0 = s0 + (s1 - s0) * pos / total
                    pos += len(t) + 1
                    items.append((t, a0, s0 + (s1 - s0) * pos / total))
            items = [x for x in items if x[0]]
            for i, (text, a0, a1) in enumerate(items):
                last = i == len(items) - 1 and si < len(segments) - 1
                words.append((text, a0, a1, b + seg["end"] if last else None))
        return words

    def _new_part(self, words):
        """Drop what was already confirmed: by time, then any overlap with the last confirmed words."""
        last_end = self.committed[-1]["audio_end"] if self.committed else 0.0
        tail = [w for w in words if w[1] > last_end - 0.1]
        done = [norm(w["word"]) for w in self.committed[-5:]]
        for k in range(min(len(done), len(tail)), 0, -1):
            if [norm(w[0]) for w in tail[:k]] == done[-k:]:
                return tail[k:]
        return tail

    def update(self, audio_all, now_audio, wall):
        start = int(self.buffer_start * RATE)
        end = int(now_audio * RATE)
        tail = self._new_part(self._run(audio_all[start:end]))
        wall_after = wall()

        # First-shown times: a word keeps its time while it stays the same in the same place.
        seen = []
        for i, w in enumerate(tail):
            if i < len(self.previous) and norm(self.previous[i][0]) == norm(w[0]):
                seen.append(self.first_seen[i])
            else:
                seen.append(wall_after)

        # LocalAgreement-2: confirm the common prefix of this run and the previous one.
        n = 0
        while n < len(tail) and n < len(self.previous) and norm(tail[n][0]) == norm(self.previous[n][0]):
            n += 1
        cut = None
        for i in range(n):
            text, a0, a1, seg_end = tail[i]
            self.committed.append({"word": text, "audio_start": round(a0, 3), "audio_end": round(a1, 3),
                                   "shown": round(seen[i], 3), "confirmed": round(wall_after, 3)})
            if seg_end is not None:
                cut = seg_end  # a whole segment is confirmed and another one follows
        self.previous, self.first_seen = tail[n:], seen[n:]

        # Too long without a safe cut: cut at the last confirmed word.
        if cut is None and now_audio - self.buffer_start > self.max_buffer and self.committed:
            cut = max(self.committed[-1]["audio_end"], self.buffer_start)
        if cut is not None and cut > self.buffer_start:
            self.buffer_start = cut
            # The tail's words started before the cut are gone from the next run's view.
            keep = [i for i, w in enumerate(self.previous) if w[1] >= cut - 0.05]
            self.previous = [self.previous[i] for i in keep]
            self.first_seen = [self.first_seen[i] for i in keep]

    def flush(self, wall):
        t = wall()
        for (text, a0, a1, _), s in zip(self.previous, self.first_seen):
            self.committed.append({"word": text, "audio_start": round(a0, 3), "audio_end": round(a1, 3),
                                   "shown": round(s, 3), "confirmed": round(t, 3)})
        self.previous, self.first_seen = [], []


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("audio")
    p.add_argument("--ref", help="correct transcript (.txt), for the word error rate")
    p.add_argument("--model", default="small", choices=MODELS)
    p.add_argument("--step", type=float, default=0.7, help="seconds between Whisper runs")
    p.add_argument("--max-buffer", type=float, default=10.0)
    p.add_argument("--word-ts", action="store_true", help="Whisper word timestamps (slower)")
    p.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results"))
    args = p.parse_args()

    audio = load_audio(args.audio)
    duration = len(audio) / RATE
    streamer = Streamer(MODELS[args.model], args.step, args.max_buffer, args.word_ts)
    print(f"Audio {duration:.1f} s. Loading {args.model} ...", file=sys.stderr)
    streamer._run(np.zeros(RATE, dtype=np.float32))  # load + warm up, not counted
    streamer.calls, streamer.compute = 0, 0.0

    cpu0 = time.process_time()
    t0 = time.monotonic()
    wall = lambda: time.monotonic() - t0
    while True:
        now = min(wall(), duration)  # audio "heard" so far, as in a live meeting
        if now - streamer.buffer_start >= 0.3:
            streamer.update(audio, now, wall)
        if now >= duration:
            break
        time.sleep(max(0.0, args.step - (wall() - now)))
    streamer.update(audio, duration, wall)
    streamer.flush(wall)

    os.makedirs(args.out, exist_ok=True)
    name = os.path.splitext(os.path.basename(args.audio))[0]
    path = os.path.join(args.out, f"{name}.whisper-{args.model}{'-wordts' if args.word_ts else ''}.jsonl")
    meta = {
        "meta": True, "audio": args.audio,
        "engine": f"whisper-{args.model}+LA2" + ("+wordts" if args.word_ts else ""),
        "duration": round(duration, 2), "step": args.step, "calls": streamer.calls,
        "compute_s": round(streamer.compute, 2), "cpu_s": round(time.process_time() - cpu0, 2),
        "wall_s": round(wall(), 2),
        "peak_mem_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576, 1),
    }
    with open(path, "w") as f:
        f.write(json.dumps(meta) + "\n")
        for w in streamer.committed:
            f.write(json.dumps(w) + "\n")
    print(f"Saved {path}", file=sys.stderr)

    score = os.path.join(os.path.dirname(__file__), "score.py")
    subprocess.run([sys.executable, score, path] + (["--ref", args.ref] if args.ref else []))


if __name__ == "__main__":
    main()
