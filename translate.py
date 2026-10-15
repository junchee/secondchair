"""Translate transcript lines English <-> Korean with Qwen via OpenRouter.

Only providers with zero data retention are used (requests fail rather than fall back).
Needs OPENROUTER_API_KEY in the environment (set in ~/.zshrc).
"""

import json
import os
import queue
import threading
import urllib.request
from collections import deque

# Cheapest Qwen that translated well in tests: $0.10/M in, $0.15/M out, about 0.45-0.6 s per
# line on ZDR providers (Oct 2026). qwen/qwen3.5-35b-a3b was similar in speed, slightly
# better wording, about 6x the output price.
MODEL = "qwen/qwen3.5-9b"
URL = "https://openrouter.ai/api/v1/chat/completions"
TARGET = {"en": "Korean", "ko": "English"}
CONTEXT_LINES = 2  # earlier lines sent along, so a line cut mid-sentence is understood


def translate(text, target, context=()):
    """Translate one line. `context` holds earlier "LABEL: text" lines, used only for meaning."""
    prompt = text
    if context:
        earlier = "\n".join(context)
        prompt = f"Earlier lines (context only, do not translate):\n{earlier}\n\nLine to translate:\n{text}"
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": f"You translate one line of a live meeting transcript into natural {target}. "
                "Lines are cut at pauses, so a line may start or end mid-sentence: use the earlier "
                "lines only to understand it, and translate the line as a fragment if it is one. "
                "Translate every word of the line, including any words in other languages; keep "
                "names of people and places. Do not translate the earlier lines. "
                "Reply with the translation only.",
            },
            {"role": "user", "content": prompt},
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
        self.recent = deque(maxlen=CONTEXT_LINES)
        threading.Thread(target=self._work, daemon=True).start()

    def submit(self, label, text, language):
        # Take the context now, in transcript order, before this line joins it.
        self.jobs.put((label, text, language, tuple(self.recent)))
        self.recent.append(f"{label}: {text}")

    def _work(self):
        while True:
            label, text, language, context = self.jobs.get()
            try:
                result = translate(text, TARGET[language], context)
            except Exception as error:  # network or API error: show it, keep going
                result = f"(translation failed: {error})"
            print(f"           {label} → {result}", flush=True)
