"""The engine for Anne.app: the app (Swift) hears the sound and turns it into text, this side only receives lines.

Same job as `Engine` in transcribe_stream.py, minus the audio: no microphone, no BlackHole, no output route and no
Whisper here. The app posts each finished line to /line (see `RemoteEngine.submit_line`); this side filters it the same
way as before, groups it into a bubble, translates it and shows it. Start, Pause and End still come from the page:
the app watches the `session` events and starts or stops listening. Run with `app.py --remote-speech`.
"""

import itertools
import queue
import re
import sys
import threading
import time

import tuning
from bubbles import Grouper
from events import Settings
from transcribe_stream import POLL_SECONDS, Hooks, drop_repeats
from textclean import strip_inline_labels
from translate import Translator

LANGUAGES = ("en", "ko")
SOURCES = {"SYSTEM", "MIC"}  # same labels as the Python engine, so the page, the recorder and the summary need no change


def keep_segments(segments):
    """Per part, like the Python engine: a part Whisper is unsure is speech AND unsure of its words is dropped."""
    kept = []
    for part in segments:
        silent, unsure = part.get("no_speech_prob"), part.get("avg_logprob")
        if silent is not None and unsure is not None and silent > tuning.get("no_speech_prob") and unsure < tuning.get("min_avg_logprob"):
            print(f"[timing] dropped as noise (no_speech_prob {silent:.2f} > {tuning.get('no_speech_prob')}, "
                  f"avg_logprob {unsure:.2f} < {tuning.get('min_avg_logprob')}): {str(part.get('text', '')).strip()[:50]!r}", file=sys.stderr, flush=True)
            continue
        kept.append(str(part.get("text", "")).strip())
    return " ".join(piece for piece in kept if piece)


def keep_text(text, avg_logprob=None, no_speech_prob=None, language_share=None):
    """The same noise rules as the Python engine's transcribe() and language check. Returns the text to show, or "" to drop it.
    The app sends Whisper's own numbers with each line; a missing number means 'no opinion'."""
    if language_share is not None and language_share < tuning.get("min_language_share"):
        print(f"[timing] dropped: neither English nor Korean (share {language_share:.2f} < {tuning.get('min_language_share')})",
              file=sys.stderr, flush=True)
        return ""
    if no_speech_prob is not None and avg_logprob is not None:
        if no_speech_prob > tuning.get("no_speech_prob") and avg_logprob < tuning.get("min_avg_logprob"):
            print(f"[timing] dropped as noise (no_speech_prob {no_speech_prob:.2f} > {tuning.get('no_speech_prob')}, "
                  f"avg_logprob {avg_logprob:.2f} < {tuning.get('min_avg_logprob')}): {text.strip()[:50]!r}", file=sys.stderr, flush=True)
            return ""
    text = drop_repeats(text.strip())
    if re.fullmatch(r"[\[\(（【].*[\]\)）】]", text):  # "[Music]", "(gentle music)", "[끝]": WhisperKit writes sounds in brackets
        print(f"[timing] dropped as a sound label: {text!r}", file=sys.stderr, flush=True)
        return ""
    text, removed = strip_inline_labels(text)  # "so [typing] we go" -> "so we go": a label inside a line would be translated as words
    if removed:
        print(f"[timing] removed {removed} sound label(s) inside a line", file=sys.stderr, flush=True)
        if not text:
            return ""
    if re.sub(r"[\W_]+", "", text).lower() in tuning.noise_phrases():
        print(f"[timing] dropped as a made-up phrase: {text!r}", file=sys.stderr, flush=True)
        return ""
    return text


class RemoteEngine:
    """idle --start--> running <--pause/resume--> paused --end--> ending --> idle, driven by the page; lines come from the app."""

    def __init__(self, settings=None, emit=print, controls=None, hooks=None):
        self.settings = settings or Settings()
        self.emit = emit
        self.hooks = hooks or Hooks()
        self.state = "idle"
        self.last_saved = None
        self.commands = queue.Queue()
        self.quit_requested = False
        self.voice_out = None
        self.line_ids = itertools.count(1)
        self.lock = threading.Lock()  # lines arrive on server threads; the meeting changes on the main thread
        self.translator = Translator(emit, lambda: self.settings.translate_model) if self.settings.translate_available else None
        self.grouper = Grouper()
        if controls is not None:
            controls["engine"] = self

    # ---- from the page (any thread)

    def command(self, action):
        if action in ("start", "pause", "resume", "end"):
            self.commands.put(action)

    def _take_id(self):
        return next(self.line_ids)

    def request_quit(self):
        self.quit_requested = True

    # ---- from the app (server threads)

    def submit_line(self, body):
        """One finished line: {"source": "SYSTEM"|"MIC", "lang": "en"|"ko", "text", "level"?, "avg_logprob"?, "no_speech_prob"?, "language_share"?}.
        False when it is malformed; a line that is dropped on purpose (paused, noise, a quiet mic) still counts as accepted."""
        if body.get("partial") and body.get("source") in SOURCES:
            return self._partial(body)
        if body.get("model") in ("loading", "ready"):  # the app loads the speech model: the page shows its banner
            self.emit({"type": "model", "state": body["model"]})
            return True
        source, language, text = body.get("source"), body.get("lang"), body.get("text")
        segments = body.get("segments")
        if isinstance(segments, list) and segments and all(isinstance(part, dict) for part in segments):
            text = keep_segments(segments) if isinstance(text, str) else text  # noise is decided part by part
            body = {**body, "avg_logprob": None, "no_speech_prob": None}
        if source not in SOURCES or language not in LANGUAGES or not isinstance(text, str):
            return False
        with self.lock:
            if self.state != "running":
                return True  # the page paused or ended: what the app heard a moment ago is not recorded
            level = float(body.get("level") or 0.0)
            if source == "MIC" and level < self.settings.mic_min_level():
                return True  # a click or room noise, not Jun
            text = keep_text(text, body.get("avg_logprob"), body.get("no_speech_prob"), body.get("language_share"))
            if not text:
                return True
            translating = self.translator is not None and self.settings.translate
            line = {"type": "line", "id": self._take_id(), "source": source, "lang": language, "text": text,
                    "time": time.strftime("%H:%M:%S")}
            if source == "MIC":
                line["level"] = round(level, 4)
            if isinstance(body.get("gap"), (int, float)):
                line["gap"] = float(body["gap"])  # seconds of quiet before this sentence: a long one starts a new bubble
            if body.get("turn"):
                line["turn"] = True  # the app heard the speaker change: this line starts a new bubble
            line["bubble"] = self.grouper.assign(line)
            line.pop("turn", None)
            line.pop("gap", None)
            self.emit(line)
            if translating:
                self.translator.submit(line)
        return True

    def _partial(self, body):
        """The sentence still being spoken: shown in grey in its bubble, replaced by the final line. {"partial": true, "source", "lang", "text"} or {"partial": true, "source", "clear": true}."""
        source = body["source"]
        with self.lock:
            if self.state != "running":
                return True
            if body.get("clear"):
                self.grouper.clear_draft(source)
                self.emit({"type": "partial", "source": source, "clear": True})
                return True
            language, text = body.get("lang"), body.get("text")
            if language not in LANGUAGES or not isinstance(text, str):
                return False
            text = text.strip()
            if not text or re.fullmatch(r"[\[\(（【].*[\]\)）】]", text):
                return True
            gap = body.get("gap") if isinstance(body.get("gap"), (int, float)) else None
            bubble, new = self.grouper.draft(source, text, language, gap, bool(body.get("turn")), self._take_id)
            if self.translator:
                self.translator.hold(bubble)   # the bubble is still growing: its translation waits
            self.emit({"type": "partial", "source": source, "lang": language, "text": text, "time": time.strftime("%H:%M:%S"),
                       "bubble": bubble, "new": new, "locked": True})
        return True

    # ---- the meeting's life (same events as Engine)

    def _set_state(self, state, **extra):
        self.state = state
        self.emit({"type": "session", "state": state, **extra})

    def _status(self):
        self.emit({"type": "status", "output": None, "kind": None, "mic": bool(self.settings.mic_enabled), "mic_available": True})

    def _handle_commands(self):
        while True:
            try:
                action = self.commands.get_nowait()
            except queue.Empty:
                return
            if action == "start" and self.state == "idle":
                self._start()
            elif action == "pause" and self.state == "running":
                self._set_state("paused")
            elif action == "resume" and self.state == "paused":
                self._set_state("running")
            elif action == "end" and self.state in ("running", "paused"):
                self._end()

    def _start(self):
        with self.lock:
            self.hooks.begin()
            self.line_ids = itertools.count(1)
            self.grouper.reset()
            if self.translator:
                self.translator.reset()
            self.emit(self.settings.as_event())  # the page was cleared by hooks.begin()
            self._status()
            self._set_state("running", new=True)

    def _end(self):
        with self.lock:
            if self.translator:
                self.translator.flush()
            self._set_state("ending")
        saved = self.hooks.finish()  # the summary can take a few seconds
        self.last_saved = saved or self.last_saved
        with self.lock:
            self._set_state("idle", saved=saved)

    def serve(self, autostart=True):
        """Run until request_quit() or Ctrl+C. A meeting still running is ended properly (summary and save)."""
        try:
            self.emit(self.settings.as_event())  # the first screen (terms, key) and the Briefing list need it before Start
            self.emit({"type": "session", "state": "idle", "fresh": True})  # waits for Start on the page
            if autostart:
                self._start()
            while not self.quit_requested:
                self._handle_commands()
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            if self.state in ("running", "paused"):
                self._end()
        return self.last_saved
