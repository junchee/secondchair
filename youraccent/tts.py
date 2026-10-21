"""Speaks one word with a Kokoro voice and keeps the sound file, so each word is made only once.

MLX must be used from one thread only, so every generation runs in one worker thread that also
loads the model. Callers wait for their file.
"""

import os
import queue
import threading
import wave

from youraccent.voices import lang_code

MODEL = "mlx-community/Kokoro-82M-bf16"
RATE = 24000
SPEEDS = {"normal": 1.0, "slow": 0.8}


class TTS:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.jobs = queue.Queue()
        self.model = None
        threading.Thread(target=self._work, daemon=True).start()

    def path(self, word, voice, speed):
        return os.path.join(self.cache_dir, voice, f"{word}_{speed}.wav")

    def get(self, word, voice, speed="normal", timeout=180):
        """The wav file for this word, made if needed. Raises RuntimeError if it cannot be made."""
        path = self.path(word, voice, speed)
        if os.path.exists(path):
            return path
        job = {"word": word, "voice": voice, "speed": speed, "path": path, "done": threading.Event(), "error": None}
        self.jobs.put(job)
        if not job["done"].wait(timeout):
            raise RuntimeError("voice took too long")
        if job["error"]:
            raise RuntimeError(job["error"])
        return path

    def _work(self):
        while True:
            job = self.jobs.get()
            try:
                if os.path.exists(job["path"]):
                    continue
                self._make(job)
            except Exception as error:  # report to the waiting caller, keep the worker alive
                job["error"] = f"{type(error).__name__}: {error}"
            finally:
                job["done"].set()

    def _make(self, job):
        import numpy as np

        if self.model is None:
            from mlx_audio.tts.utils import load_model

            self.model = load_model(MODEL)
        chunks = [
            np.array(r.audio, dtype=np.float32)
            for r in self.model.generate(
                text=job["word"].capitalize() + ".",
                voice=job["voice"],
                speed=SPEEDS[job["speed"]],
                lang_code=lang_code(job["voice"]),
            )
        ]
        if not chunks:
            raise RuntimeError("no sound was made")
        audio = np.concatenate(chunks)
        os.makedirs(os.path.dirname(job["path"]), mode=0o700, exist_ok=True)
        tmp = job["path"] + ".tmp"
        with wave.open(tmp, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        os.replace(tmp, job["path"])
