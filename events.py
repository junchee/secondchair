"""Events from the transcriber, translator and router.

Every component reports through an `emit(event)` callable; the terminal and the browser
(app.py) are just two consumers of the same events. An event is a dict with a "type":

    line         id, source ("SYSTEM" or "MIC"), lang ("en"/"ko"), text, time ("HH:MM:SS")
    translation  id (of the line), text, revised (True when redone with the next line)
    status       output (device name or None), kind ("headphones"/"speakers"/None), mic (bool)
    settings     translate, translate_available, max_line_seconds, pause_seconds, mic_filter
    line         also has level (speech RMS of the segment) for MIC lines, to tune mic_filter
    voice        available, mode ("direct"/"interpret"), device, voice (id), voices (list of
                 id, name, language, gender, quality), monitor, monitor_volume (see voice_out.py)
    draft        text (English waiting for Jun to confirm; "" when cleared)
    spoken       text, seconds (sent into the meeting by voice)
    summarizing  final (a summary is being made)
    summary      text (Markdown; "" when nothing was said yet), final (False while the meeting
                 goes on), time ("HH:MM")
    asking       id, question (Jun's question about the meeting; the answer is on the way)
    answer       id, question, text (Korean, from the conversation so far; not recorded)
    typing       id, source (text Jun typed; its translation is on the way)
    typed        id, source, text (translation), target ("English"/"Korean"/None on failure)
    info         text
"""

import os

import prefs

# Line cutting: a line ends after this much silence, or at the maximum length.
LIMITS = {"max_line_seconds": (4.0, 20.0), "pause_seconds": (0.2, 1.5)}

# Sounds from the mic quieter than this are not treated as Jun speaking. Whisper writes
# "Thank you." for key clicks and room noise, and each such line also costs a translation.
MIC_FILTER_LEVELS = {"off": 0.0, "normal": 0.006, "strong": 0.015}


class Settings:
    """What the user can change while secondchair runs (read by other threads as it changes).

    With persist=True the values are loaded from user_settings.json at the start and saved
    whenever the page changes one (see prefs.py).
    """

    def __init__(self, translate=False, max_line_seconds=10.0, pause_seconds=0.5, persist=False):
        self.persist = persist
        self.translate_available = bool(os.environ.get("OPENROUTER_API_KEY"))
        self.translate = translate and self.translate_available
        self.max_line_seconds = max_line_seconds
        self.pause_seconds = pause_seconds
        self.mic_filter = "normal"
        if persist:
            self._apply(prefs.load())

    def mic_min_level(self):
        """Quietest speech-frame RMS that still counts as Jun speaking."""
        return MIC_FILTER_LEVELS[self.mic_filter]

    def _apply(self, change):
        """Take over the values in `change`; unknown or bad ones are ignored, numbers clamped."""
        if isinstance(change.get("translate"), bool):
            self.translate = change["translate"] and self.translate_available
        if change.get("mic_filter") in MIC_FILTER_LEVELS:
            self.mic_filter = change["mic_filter"]
        for key, (low, high) in LIMITS.items():
            if key in change:
                try:
                    setattr(self, key, min(high, max(low, float(change[key]))))
                except (TypeError, ValueError):
                    pass

    def update(self, change):
        """Apply a change from the page, and remember it for the next run."""
        self._apply(change)
        if self.persist:
            prefs.save(
                translate=self.translate if self.translate_available else prefs.load().get("translate", True),
                max_line_seconds=self.max_line_seconds,
                pause_seconds=self.pause_seconds,
                mic_filter=self.mic_filter,
            )

    def as_event(self):
        return {
            "type": "settings",
            "translate": self.translate,
            "translate_available": self.translate_available,
            "max_line_seconds": self.max_line_seconds,
            "pause_seconds": self.pause_seconds,
            "mic_filter": self.mic_filter,
        }


def print_event(event):
    """Render an event as a terminal line."""
    kind = event["type"]
    if kind == "line":
        print(f"[{event['time']}] {event['source']}: {event['text']}", flush=True)
    elif kind == "translation":
        note = " (revised)" if event.get("revised") else ""
        print(f"           #{event['id']}{note} → {event['text']}", flush=True)
    elif kind == "status":
        output = f"{event['output']} + BlackHole, {event['kind']}" if event["output"] else "not switched"
        print(f"[output: {output} | mic {'on' if event['mic'] else 'off'}]", flush=True)
    elif kind == "settings":
        print(
            f"[translation {'on' if event['translate'] else 'off'} | lines end after "
            f"{event['pause_seconds']} s pause, max {event['max_line_seconds']} s]",
            flush=True,
        )
    elif kind == "voice":
        state = f"{event['mode']} via {event['device']}" if event["available"] else f"{event['device']} not installed"
        print(f"[voice: {state}]", flush=True)
    elif kind == "draft":
        print(f"[draft: {event['text']}]" if event["text"] else "[draft cleared]", flush=True)
    elif kind == "spoken":
        print(f"[spoken ({event['seconds']} s): {event['text']}]", flush=True)
    elif kind == "summarizing":
        print("[summarizing the meeting…]" if event["final"] else "[summarizing so far…]", flush=True)
    elif kind == "summary":
        if not event["text"]:
            print("[nothing to summarize yet]", flush=True)
        else:
            title = "Meeting summary" if event["final"] else f"Summary so far ({event['time']})"
            print(f"\n== {title} ==\n{event['text']}\n", flush=True)
    elif kind == "answer":
        print(f"[ask: {event['question']} → {event['text']}]", flush=True)
    elif kind == "typed":
        print(f"[typed: {event['source']} → {event['text']}]", flush=True)
    elif kind == "info":
        print(f"[{event['text']}]", flush=True)


def fan_out(*consumers):
    """One emit that sends each event to several consumers."""

    def emit(event):
        for consumer in consumers:
            consumer(event)

    return emit
