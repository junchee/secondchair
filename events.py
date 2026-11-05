"""Events from the transcriber, translator and router.

Every component reports through an `emit(event)` callable; the terminal and the browser
(app.py) are just two consumers of the same events. An event is a dict with a "type":

    line         id, source ("SYSTEM" or "MIC"), lang ("en"/"ko"), text, time ("HH:MM:SS")
    translation  id (of the bubble = its first line), ids (all its lines so far), text, revised (True when
                 redone because the bubble grew). A line event also carries bubble (see bubbles.py).
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
    partial      source, text, time or clear: a line that is still being spoken (Them only; the text is
                 empty for now). The page shows an outlined bubble until the final line replaces it.
    translation_partial   id (of the bubble), text: the translation so far while it is still arriving.
                 The final translation event follows and replaces it.

partial and translation_partial are short-lived: they are not kept for the page's replay, not
saved in the transcript and not used for the voice draft.
"""

import os

import time

import models
import prefs
import tuning
import prep
import translate

# Events that only matter at the moment they happen.
VOLATILE = ("partial", "translation_partial", "prep_result")

# Line cutting: a line ends after this much silence, or at the maximum length.
LIMITS = {"max_line_seconds": (4.0, 20.0), "pause_seconds": (0.2, 1.5)}

# Sounds from the mic quieter than this are not treated as Jun speaking. Whisper writes
# "Thank you." for key clicks and room noise, and each such line also costs a translation.
MIC_FILTER_LEVELS = {"off": 0.0, "normal": 0.006, "strong": 0.015}

# Which model translates the bubbles: DeepSeek with Qwen as the backup (auto), or one of them alone.
TRANSLATION_MODES = ("auto", "deepseek", "qwen")


MAX_BRIEFINGS = 3  # briefings that can be used together in one meeting


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
        self.translate_model = "auto"
        self.mic_enabled = True  # the mic button in the top menu: off = my microphone is not listened to
        # 배경지식: a list Jun keeps; ONE is chosen for each meeting when it starts (never applied by itself).
        # meeting_topic and terms are those of the chosen one (empty when none is chosen).
        self.backgrounds = []        # {"id", "title", "text", "topic", "terms", "updated", "used"}
        self.active_backgrounds = []   # up to MAX_BRIEFINGS ids chosen for this meeting
        self.meeting_topic = ""
        self.terms = []
        self.summarize_at_end = True  # End asks "요약할까요?"; False = end and save without a summary
        if persist:
            saved = prefs.load()
            self._apply(saved)
            tuning.apply(saved.get("tuning"))
            self._load_backgrounds(saved)

    def mic_min_level(self):
        """Quietest speech-frame RMS that still counts as Jun speaking."""
        return MIC_FILTER_LEVELS[self.mic_filter]

    def _apply(self, change):
        """Take over the values in `change`; unknown or bad ones are ignored, numbers clamped."""
        if isinstance(change.get("translate"), bool):
            self.translate = change["translate"] and self.translate_available
        if change.get("mic_filter") in MIC_FILTER_LEVELS:
            self.mic_filter = change["mic_filter"]
        if isinstance(change.get("mic_enabled"), bool):
            self.mic_enabled = change["mic_enabled"]
        if change.get("translate_model") in TRANSLATION_MODES:
            self.translate_model = change["translate_model"]
        if isinstance(change.get("tuning"), dict):
            tuning.apply(change["tuning"])
        if change.get("tuning_reset"):
            tuning.reset(str(change["tuning_reset"]))
        translate.set_meeting(self.meeting_topic, self.terms)
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
                translate_model=self.translate_model,
                mic_enabled=self.mic_enabled,
                backgrounds=self.backgrounds,
                tuning=tuning.changed(),
            )

    # ---- 배경지식 list
    def _load_backgrounds(self, saved):
        items = saved.get("backgrounds")
        if not isinstance(items, list):
            # first run of this version: the one background kept so far becomes the first item (the old keys stay in the file)
            text, topic, terms = saved.get("meeting_context", ""), saved.get("meeting_topic", ""), saved.get("terms", [])
            items = [{"id": "b0", "title": topic or text[:40], "text": text, "topic": topic, "terms": terms,
                      "updated": time.strftime("%Y-%m-%d %H:%M"), "used": ""}] if text.strip() or terms else []
        self.backgrounds = [self._clean_background(i) for i in items if isinstance(i, dict) and i.get("id")]
        if "backgrounds" not in saved:
            self.update({})

    @staticmethod
    def _clean_background(item):
        return {
            "id": str(item["id"])[:20],
            "title": str(item.get("title", ""))[:80],
            "text": str(item.get("text", ""))[:8000],
            "topic": str(item.get("topic", ""))[:200],
            "terms": prep.clean_terms(item.get("terms")),
            "updated": str(item.get("updated", ""))[:20],
            "used": str(item.get("used", ""))[:20],
        }

    def recent_background(self):
        """The id used most recently (else the newest saved), or None: the default choice at Start."""
        used = [b for b in self.backgrounds if b["used"]]
        pool = used or self.backgrounds
        if not pool:
            return None
        return max(pool, key=lambda b: (b["used"], b["updated"]))["id"]

    def save_background(self, item):
        """Create or change one background; returns its id. Only the fields given are changed."""
        found = next((b for b in self.backgrounds if b["id"] == item.get("id")), None)
        if found is None:
            found = {"id": "b%x" % int(time.time() * 1000), "title": "", "text": "", "topic": "", "terms": [], "updated": "", "used": ""}
            self.backgrounds.append(found)
        for key in ("title", "text", "topic", "terms"):
            if key in item:
                found[key] = item[key]
        found.update(self._clean_background(found))
        found["updated"] = time.strftime("%Y-%m-%d %H:%M")
        self.update({})
        return found["id"]

    def delete_background(self, background_id):
        self.backgrounds = [b for b in self.backgrounds if b["id"] != background_id]
        if background_id in self.active_backgrounds:
            self.use_backgrounds([i for i in self.active_backgrounds if i != background_id])
        self.update({})

    def use_backgrounds(self, ids):
        """Choose the briefings for this meeting (up to MAX_BRIEFINGS; [] = none): their topics are joined and their terms
        merged (the same English term once), and go to Whisper and the translation from the next line on."""
        chosen = []
        for background_id in ids or []:
            found = next((b for b in self.backgrounds if b["id"] == background_id), None)
            if found and found not in chosen:
                chosen.append(found)
        chosen = chosen[:MAX_BRIEFINGS]
        self.active_backgrounds = [b["id"] for b in chosen]
        self.meeting_topic = "; ".join(b["topic"] for b in chosen if b["topic"])[:300]
        merged, seen = [], set()
        for b in chosen:
            for term in b["terms"]:
                if term["en"].lower() not in seen:
                    seen.add(term["en"].lower())
                    merged.append(term)
        self.terms = merged
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for b in chosen:
            b["used"] = now
        translate.set_meeting(self.meeting_topic, self.terms)
        self.update({})

    def as_event(self):
        return {
            "type": "settings",
            "translate": self.translate,
            "translate_available": self.translate_available,
            "max_line_seconds": self.max_line_seconds,
            "pause_seconds": self.pause_seconds,
            "mic_filter": self.mic_filter,
            "translate_model": self.translate_model,
            "mic_enabled": self.mic_enabled,
            "backgrounds": self.backgrounds,
            "recent_background": self.recent_background(),
            "active_backgrounds": self.active_backgrounds,
            "max_briefings": MAX_BRIEFINGS,
            "tuning": {"groups": tuning.GROUPS, "schema": tuning.SCHEMA, "values": tuning.values()},
            "models": models.status(),
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
