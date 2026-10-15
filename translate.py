"""Translate transcript lines English <-> Korean with Qwen via OpenRouter.

Only providers with zero data retention are used (requests fail rather than fall back).
Needs OPENROUTER_API_KEY in the environment (set in ~/.zshrc).
"""

import http.client
import json
import os
import queue
import threading
import unicodedata
from collections import deque

# Cheapest Qwen that translated well in tests: $0.10/M in, $0.15/M out, about 0.45-0.6 s per
# line on ZDR providers (Oct 2026). qwen/qwen3.5-35b-a3b was similar in speed, slightly
# better wording, about 6x the output price.
MODEL = "qwen/qwen3.5-9b"
# The small model sometimes slips other scripts into Korean ("毛毛비" for drizzle, a Japanese
# clause, "아нди") even when told not to; such lines are redone once with this one.
FALLBACK_MODEL = "qwen/qwen3.5-35b-a3b"
HOST = "openrouter.ai"
PATH = "/api/v1/chat/completions"
TARGET = {"en": "Korean", "ko": "English"}
CONTEXT_LINES = 2  # earlier lines sent along, so a line cut mid-sentence is understood


# Whisper rarely puts a full stop on Korean, so a Korean line also counts as finished when it
# ends in a common sentence ending ("-다", "-요", "-죠", "-까", "-자" ...). Without this nearly
# every Korean line would be translated twice, and the second time can come out worse.
KOREAN_ENDINGS = "다요죠까네야어지자나군래"


def ends_sentence(text):
    text = text.rstrip()
    if text.endswith("...") or text.endswith("…"):
        return False
    if text.endswith((".", "?", "!", "。", "？", "！")):
        return True
    return bool(text) and text[-1] in KOREAN_ENDINGS


def has_foreign_script(text):
    """True if `text` has a letter that is neither Hangul nor Latin (kana, Chinese, Cyrillic, Thai ...).
    A Korean translation may keep Latin names ("BBC"), but the small model sometimes slips other
    scripts into it ("毛毛비", a Japanese clause, "코르นว얼")."""
    for ch in text:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            if not (name.startswith("HANGUL") or name.startswith("LATIN")):
                return True
    return False


def build_request(text, target, context=(), following=None, model=MODEL):
    """Chat request for one line. `context` holds earlier "LABEL: text" lines and `following`
    the next line; both are only there to make the meaning of a cut line clear."""
    parts = []
    if context:
        parts.append("Earlier lines (context only, do not translate):\n" + "\n".join(context))
    parts.append("Line to translate:\n" + text)
    if following:
        parts.append("Next line (context only, do not translate):\n" + following)
    script = " Write Korean in Hangul only; never use Chinese, Japanese or Cyrillic characters." if target == "Korean" else ""
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": f"You translate one line of a live meeting transcript into natural {target}. "
                "Lines are cut at pauses, so a line may start or end mid-sentence: use the context "
                "lines only to understand it, and translate the line as a fragment if it is one. "
                "If the line stops mid-sentence, stop your translation at the same point and end it "
                "with '…'. Never add anything that is said only in a context line, even to finish "
                "a sentence: those words get their own translation. "
                "Translate every word of the line, including any words in other languages; keep "
                "names of people and places." + script + " Reply with the translation only.",
            },
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        "temperature": 0,
        "max_tokens": 300,
        "reasoning": {"enabled": False},
        "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
    }


class Client:
    """One HTTPS connection kept open between requests, so each line skips the TLS handshake."""

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.connection = None

    def post(self, body):
        payload = json.dumps(body).encode()
        headers = {
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
        }
        for attempt in (1, 2):  # the server may have closed an idle connection: reconnect once
            if self.connection is None:
                self.connection = http.client.HTTPSConnection(HOST, timeout=self.timeout)
            try:
                self.connection.request("POST", PATH, payload, headers)
                response = self.connection.getresponse()
                data = response.read()
            except (http.client.HTTPException, OSError):
                self.connection.close()
                self.connection = None
                if attempt == 2:
                    raise
                continue
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}: {data[:200].decode(errors='replace')}")
            return json.loads(data)["choices"][0]["message"]["content"].strip()


def translate(text, target, context=(), following=None, client=None):
    client = client or Client()
    result = client.post(build_request(text, target, context, following))
    if target == "Korean" and has_foreign_script(result):
        result = client.post(build_request(text, target, context, following, FALLBACK_MODEL))
    return result


def has_hangul(text):
    return any("가" <= ch <= "힣" for ch in text)


def translate_typed(text, conversation="", client=None):
    """Something Jun typed, to say himself: Korean -> English he can read aloud, or English ->
    Korean to check what his English means. `conversation` is the recent transcript, used only
    for names, terms and what "it" or "that" refers to. Returns (target, translation)."""
    target = "English" if has_hangul(text) else "Korean"
    if target == "English":
        style = (
            "Jun typed this in Korean and will read your English aloud in the meeting himself. "
            "Write short, natural spoken English that is easy to say."
        )
    else:
        style = "Jun typed this English to check its meaning. Translate it into natural Korean."
    script = " Write Korean in Hangul only; never use Chinese, Japanese or Cyrillic characters." if target == "Korean" else ""
    parts = []
    if conversation:
        parts.append("Recent conversation (context only, do not translate):\n" + conversation)
    parts.append("Text:\n" + text)

    def request(model):
        return {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": f"{style} Use the conversation only to get names, terms and "
                    "references right. Keep the meaning; do not add anything." + script
                    + " Reply with the translation only.",
                },
                {"role": "user", "content": "\n\n".join(parts)},
            ],
            "temperature": 0,
            "max_tokens": 400,
            "reasoning": {"enabled": False},
            "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
        }

    client = client or Client()
    result = client.post(request(MODEL))
    if target == "Korean" and has_foreign_script(result):
        result = client.post(request(FALLBACK_MODEL))
    return target, result


class Translator:
    """Translates line events in a background thread, so transcription never waits for the network.

    When a line ends mid-sentence, it is translated again once the next line from the same
    speaker arrives, with that line as context, and sent as a revised translation.
    """

    def __init__(self, emit):
        self.emit = emit
        self.client = Client()
        self.jobs = queue.Queue()
        self.recent = deque(maxlen=CONTEXT_LINES)  # "LABEL: text" of the latest lines
        self.last = {}  # source -> (line, context) of that speaker's latest line
        self.shown = {}  # line id -> the translation the page shows now
        threading.Thread(target=self._work, daemon=True).start()

    def reset(self):
        """A new meeting starts: its first lines must not borrow context from the last one."""
        self.recent.clear()
        self.last.clear()
        self.shown.clear()

    def submit(self, line):
        source = line["source"]
        previous = self.last.get(source)
        if previous and previous[0]["lang"] == line["lang"] and not ends_sentence(previous[0]["text"]):
            self.jobs.put((previous[0], previous[1], line["text"], True))
        # Take the context now, in transcript order, before this line joins it.
        context = tuple(self.recent)
        self.jobs.put((line, context, None, False))
        self.last[source] = (line, context)
        self.recent.append(f"{source}: {line['text']}")

    def _work(self):
        while True:
            line, context, following, revised = self.jobs.get()
            target = TARGET[line["lang"]]
            try:
                text = translate(line["text"], target, context, following, self.client)
            except Exception as error:  # network or API error: show it, keep going
                text = f"(translation failed: {error})"
            if revised and self.shown.get(line["id"]) == text:
                continue  # the same words again: nothing to update on the page
            self.shown[line["id"]] = text
            self.emit({"type": "translation", "id": line["id"], "text": text, "revised": revised})
