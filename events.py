"""Events from the transcriber, translator and router.

Every component reports through an `emit(event)` callable; the terminal and the browser
(app.py) are just two consumers of the same events. An event is a dict with a "type":

    line         id, source ("SYSTEM" or "MIC"), lang ("en"/"ko"), text, time ("HH:MM:SS")
    translation  id (of the line), text, revised (True when redone with the next line)
    status       output (device name or None), kind ("headphones"/"speakers"/None), mic (bool)
    settings     translate (bool), translate_available (bool)
    info         text
"""

import os


class Settings:
    """What the user can change while secondchair runs."""

    def __init__(self, translate=False):
        self.translate_available = bool(os.environ.get("OPENROUTER_API_KEY"))
        self.translate = translate and self.translate_available

    def as_event(self):
        return {
            "type": "settings",
            "translate": self.translate,
            "translate_available": self.translate_available,
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
        print(f"[translation {'on' if event['translate'] else 'off'}]", flush=True)
    elif kind == "info":
        print(f"[{event['text']}]", flush=True)


def fan_out(*consumers):
    """One emit that sends each event to several consumers."""

    def emit(event):
        for consumer in consumers:
            consumer(event)

    return emit
