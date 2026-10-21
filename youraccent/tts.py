"""Speaks a word or a sentence with a Kokoro voice and keeps the sound file, so each is made once.

The work runs on the shared worker thread (MLX must stay in one thread); callers wait for it.
"""

import hashlib
import os
import re
import wave

from youraccent.voices import lang_code

MODEL = "mlx-community/Kokoro-82M-bf16"
RATE = 24000
SPEEDS = {"normal": 1.0, "slow": 0.8}
WORD = re.compile(r"[A-Za-z']{1,24}")
MAX_TEXT = 400


class TTS:
    def __init__(self, cache_dir, worker):
        self.cache_dir = cache_dir
        self.worker = worker
        self.model = None

    @staticmethod
    def valid(text):
        text = text.strip()
        return 0 < len(text) <= MAX_TEXT and "\n" not in text

    def key(self, text):
        text = text.strip()
        if WORD.fullmatch(text):
            return text.lower()  # a single word: the same file name the listening training uses
        return "s_" + hashlib.sha1(text.encode()).hexdigest()[:16]

    def path(self, text, voice, speed):
        return os.path.join(self.cache_dir, voice, f"{self.key(text)}_{speed}.wav")

    def get(self, text, voice, speed="normal", timeout=300):
        """The wav file for this word or sentence, made if needed. Raises if it cannot be made."""
        text = text.strip()
        path = self.path(text, voice, speed)
        if os.path.exists(path):
            return path
        self.worker.run(lambda: self._make(text, voice, speed, path), timeout)
        return path

    def _make(self, text, voice, speed, path):  # runs on the worker thread
        import numpy as np

        if os.path.exists(path):
            return
        if self.model is None:
            from mlx_audio.tts.utils import load_model

            self.model = load_model(MODEL)
        spoken = text.capitalize() + "." if WORD.fullmatch(text) else text
        chunks = [
            np.array(r.audio, dtype=np.float32)
            for r in self.model.generate(text=spoken, voice=voice, speed=SPEEDS[speed], lang_code=lang_code(voice))
        ]
        if not chunks:
            raise RuntimeError("no sound was made")
        audio = np.concatenate(chunks)
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        tmp = path + ".tmp"
        with wave.open(tmp, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        os.replace(tmp, path)
