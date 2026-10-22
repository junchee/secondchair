"""Translate transcript lines English <-> Korean with Qwen via OpenRouter.

Only providers with zero data retention are used (requests fail rather than fall back).
Needs OPENROUTER_API_KEY in the environment (set in ~/.zshrc).
"""

import http.client
import json
import os
import queue
import threading
import sys
import time
import traceback
import unicodedata
import ssl
from collections import OrderedDict, deque

# Cheapest Qwen that translated well in tests: $0.10/M in, $0.15/M out, about 0.45-0.6 s per
# line on ZDR providers (Oct 2026). qwen/qwen3.5-35b-a3b was similar in speed, slightly
# better wording, about 6x the output price.
MODEL = "qwen/qwen3.5-9b"
# The small model sometimes slips other scripts into Korean ("毛毛비" for drizzle, a Japanese
# clause, "아нди") even when told not to; such lines are redone once with this one.
FALLBACK_MODEL = "qwen/qwen3.5-35b-a3b"
# The bubbles are translated by DeepSeek: fastest and cleanest of the three tried on 2026-10-22
# (Qwen and Haiku too); the comparison is in notes/translation_models_2026-10-22.md.
BUBBLE_MODEL = "deepseek/deepseek-v4.1-flash-1017"
# Trust the certifi certificate list, not the Python build's own setting. Some Python builds
# (the standalone ones `uv` installs) have no system certificates, and the request then fails
# with CERTIFICATE_VERIFY_FAILED. certifi comes with requests, which mlx-whisper needs anyway.
try:
    import certifi

    TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS = ssl.create_default_context()
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


def build_request(text, target, context=(), following=None, model=MODEL, previous=None):
    """Chat request for one line. `context` holds earlier "LABEL: text" lines and `following`
    the next line; both are only there to make the meaning of a cut line clear."""
    parts = []
    if context:
        parts.append("Earlier lines (context only, do not translate):\n" + "\n".join(context))
    parts.append("Line to translate:\n" + text)
    if previous:
        parts.append(
            "Your earlier translation of the beginning of this line (the line has grown since). Keep its wording "
            "for everything that has not changed and add the translation of the new words; change the earlier "
            "wording only if it was wrong:\n" + previous
        )
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


STREAM_DEADLINE_SECONDS = 8


class StreamStalled(Exception):
    pass


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
                self.connection = http.client.HTTPSConnection(HOST, timeout=self.timeout, context=TLS)
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


    def stream(self, body, on_text, interval=0.08):
        """Like post(), but asks for the answer to arrive in pieces and calls on_text(text so far) as it
        grows (at most every `interval` seconds). Returns the whole text. The connection is reused."""
        payload = json.dumps(dict(body, stream=True)).encode()
        headers = {
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        for attempt in (1, 2):
            if self.connection is None:
                self.connection = http.client.HTTPSConnection(HOST, timeout=self.timeout, context=TLS)
            try:
                self.connection.request("POST", PATH, payload, headers)
                response = self.connection.getresponse()
                if response.status != 200:
                    data = response.read()
                    raise RuntimeError(f"HTTP {response.status}: {data[:200].decode(errors='replace')}")
                text, last = "", 0.0
                deadline = time.monotonic() + STREAM_DEADLINE_SECONDS
                while True:
                    raw = response.readline()
                    if not raw:
                        break
                    if time.monotonic() > deadline:
                        # OpenRouter keeps sending keep-alive comments while a provider stalls, so the socket
                        # timeout never fires: give up on our own, or the translator waits here for ever.
                        raise StreamStalled(f"no complete answer in {STREAM_DEADLINE_SECONDS} s")
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue  # a comment or a keep-alive
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
                    except (ValueError, KeyError, IndexError):
                        continue
                    if delta:
                        text += delta
                        now = time.monotonic()
                        if now - last >= interval:
                            last = now
                            on_text(text.strip())
                response.read()  # finish the response so the connection can be used again
                return text.strip()
            except StreamStalled:
                self.connection.close()
                self.connection = None
                raise  # no second try: translate() asks once more without streaming
            except (http.client.HTTPException, OSError):
                self.connection.close()
                self.connection = None
                if attempt == 2:
                    raise
            except RuntimeError:
                raise


def translate(text, target, context=(), following=None, client=None, on_text=None, model=MODEL, previous=None):
    """The translation of one line. With on_text, it is asked for in pieces and on_text(text so far)
    is called while it arrives (the page shows the Korean from the first word)."""
    client = client or Client()
    body = build_request(text, target, context, following, model, previous)
    if on_text:
        show, stopped = on_text, []

        def on_text(partial):  # a partial with another script in it is not shown: the redo below replaces it
            if stopped or (target == "Korean" and has_foreign_script(partial)):
                stopped.append(True)
                return
            show(partial)

        try:
            result = client.stream(body, on_text)
        except Exception:
            result = client.post(body)  # streaming did not work: the plain request still can
    else:
        result = client.post(body)
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
    """Translates bubbles in a background thread, so transcription never waits for the network.

    A bubble (see bubbles.py) is translated as a whole. While it grows, only its newest text is
    kept waiting: an older waiting version is replaced, so the queue cannot fall behind. The page
    keeps showing the previous translation until the new one arrives.
    """

    def __init__(self, emit):
        self.emit = emit
        self.client = Client(timeout=10)  # a bubble translation takes about a second; 10 s means it is stuck
        self.cv = threading.Condition()
        self.waiting = OrderedDict()  # bubble id -> job, oldest first
        self.recent = deque(maxlen=CONTEXT_LINES)  # [bubble id, "LABEL: text"] of the latest bubbles
        self.bubbles = {}  # bubble id -> {"ids", "text", "lang", "context", "version"}
        self.shown = {}  # bubble id -> the translation the page shows now
        threading.Thread(target=self._work, daemon=True).start()

    def reset(self):
        """A new meeting starts: its first lines must not borrow context from the last one."""
        with self.cv:
            self.waiting.clear()
            self.recent.clear()
            self.bubbles.clear()
            self.shown.clear()

    def submit(self, line):
        bid = line.get("bubble", line["id"])
        with self.cv:
            bubble = self.bubbles.get(bid)
            if bubble is None:
                # The context is taken now, in transcript order, before this bubble joins it.
                context = tuple(text[-300:] for _, text in self.recent)
                bubble = {"ids": [], "text": "", "lang": line["lang"], "context": context, "version": 0}
                self.bubbles[bid] = bubble
                self.recent.append([bid, ""])
            bubble["ids"].append(line["id"])
            bubble["text"] = (bubble["text"] + " " + line["text"]).strip()
            for entry in self.recent:
                if entry[0] == bid:
                    entry[1] = f"{line['source']}: {bubble['text']}"
            bubble["version"] += 1
            self.waiting[bid] = (bid, bubble["text"], bubble["lang"], bubble["context"], tuple(bubble["ids"]), bubble["version"])
            self.cv.notify()

    def _work(self):
        while True:
            try:
                self._translate_next()
            except Exception:  # one bad job must never stop the translator for the rest of the meeting
                traceback.print_exc()

    def _translate_next(self):
        with self.cv:
            while not self.waiting:
                self.cv.wait()
            bid, text, lang, context, ids, version = self.waiting.popitem(last=False)[1]
            previous = self.shown.get(bid)  # what the page shows for this bubble now: keep its wording
            if previous and previous.startswith("(translation failed"):
                previous = None
            queued = len(self.waiting)
        started = time.time()
        try:
            # The first translation of a bubble arrives piece by piece (the page shows the Korean from the
            # first word); a later one is not streamed: its text would shrink and grow under the reader's eyes.
            partial = None if version > 1 else (lambda part, id=bid: self.emit({"type": "translation_partial", "id": id, "text": part}))
            result = translate(text, TARGET[lang], context, None, self.client, on_text=partial, model=BUBBLE_MODEL, previous=previous)
        except Exception as error:  # network or API error: show it, keep going
            result = f"(translation failed: {error})"
        print(f"[timing] {BUBBLE_MODEL.split('/')[-1]} bubble #{bid} v{version} translated in {time.time() - started:.1f}s, {queued} bubbles waiting", file=sys.stderr, flush=True)
        if version > 1 and self.shown.get(bid) == result:
            return  # the same words again: nothing to update on the page
        self.shown[bid] = result
        self.emit({"type": "translation", "id": bid, "ids": list(ids), "text": result, "revised": version > 1})
