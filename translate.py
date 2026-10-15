"""Translate transcript lines English <-> Korean with Qwen via OpenRouter.

Only providers with zero data retention are used (requests fail rather than fall back).
Needs OPENROUTER_API_KEY in the environment (set in ~/.zshrc).
"""

import json
import os
import queue
import threading
import urllib.request

# Cheapest Qwen that translated well in tests: $0.10/M in, $0.15/M out, about 0.45-0.6 s per
# line on ZDR providers (Oct 2026). qwen/qwen3.5-35b-a3b was similar in speed, slightly
# better wording, about 6x the output price.
MODEL = "qwen/qwen3.5-9b"
URL = "https://openrouter.ai/api/v1/chat/completions"
TARGET = {"en": "Korean", "ko": "English"}


def translate(text, target):
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": f"Translate the user's text into natural {target}. "
                "It is one line of a live meeting transcript and may be cut mid-sentence. "
                "Reply with the translation only.",
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 300,
        "reasoning": {"enabled": False},
        "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
    }
    request = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)["choices"][0]["message"]["content"].strip()


class Translator:
    """Translates lines in a background thread so transcription never waits for the network."""

    def __init__(self):
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise SystemExit("OPENROUTER_API_KEY is not set. Open a new terminal or run: source ~/.zshrc")
        self.jobs = queue.Queue()
        threading.Thread(target=self._work, daemon=True).start()

    def submit(self, label, text, language):
        self.jobs.put((label, text, language))

    def _work(self):
        while True:
            label, text, language = self.jobs.get()
            try:
                result = translate(text, TARGET[language])
            except Exception as error:  # network or API error: show it, keep going
                result = f"(translation failed: {error})"
            print(f"           {label} → {result}", flush=True)
