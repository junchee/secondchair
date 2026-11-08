"""Which lines belong to one bubble: a line cut in the middle of a sentence (short pause, longest-line
setting, or a full stop Whisper put on a mere pause) continues its speaker's open bubble.

A bubble is named by the id of its first line; every line event carries it as "bubble".
"""
import tuning
from translate import ends_sentence

MAX_BUBBLE_CHARS = 500


class Grouper:
    def __init__(self):
        self.reset()

    def reset(self):
        self.open = {}  # source -> {"id": first line id, "text": text so far, "lang": ...}
        self.last_source = None
        self.locked = {}  # source -> {"bubble": id, "new": bool, "lang"}: where the grey draft now shown will land

    def assign(self, line, bubble_ids=None):
        """Return the bubble id for this line (a line event, with its id already set).
        If a grey draft was shown for this source, the line goes where the draft went (the decision is made once, at the
        draft's first appearance); a speaker change or another language is the only reason to leave it."""
        source = line["source"]
        if self.last_source not in (None, source):
            self.open.pop(self.last_source, None)  # the other side spoke in between: that bubble is closed
            self.locked.pop(self.last_source, None)
        self.last_source = source
        current = self.open.get(source)
        lock = self.locked.pop(source, None)
        if lock and lock["lang"] == line["lang"] and (lock["new"] or not line.get("turn")):
            if lock["new"] or not current or current["id"] != lock["bubble"]:
                self.open[source] = {"id": lock["bubble"], "text": line["text"], "lang": line["lang"]}
            else:
                current["text"] += " " + line["text"]
            return lock["bubble"]
        if current and not line.get("turn") and self._continues(current, line):   # "turn": the speaker changed
            current["text"] += " " + line["text"]
            return current["id"]
        self.open[source] = {"id": line["id"], "text": line["text"], "lang": line["lang"]}
        return line["id"]

    def draft(self, source, text, lang, gap, turn, new_id):   # new_id: a function that gives a fresh bubble id
        """The bubble a grey draft is shown in (existing id, or new_id() for a new bubble). Decided at the draft's first
        appearance and kept while the draft changes; decided again only after a line used it, when the speaker change
        is marked late, or when the language changes. Returns (bubble id, is_new)."""
        lock = self.locked.get(source)
        if lock and lock["lang"] == lang and (lock["new"] or not turn):
            return lock["bubble"], lock["new"]
        current = self.open.get(source)
        join = bool(current) and self.last_source in (None, source) and not turn \
            and self._continues(current, {"lang": lang, "text": text, "gap": gap})
        bubble = current["id"] if join else new_id()
        self.locked[source] = {"bubble": bubble, "new": not join, "lang": lang}
        return bubble, not join

    def clear_draft(self, source):
        self.locked.pop(source, None)

    def peek(self, source, text, lang, gap=None, turn=False):
        """The bubble that a line with this text would join (its id), or None if it would start a new one."""
        current = self.open.get(source)
        if not current or self.last_source not in (None, source) or turn:
            return None
        return current["id"] if self._continues(current, {"lang": lang, "text": text, "gap": gap}) else None

    @staticmethod
    def _continues(current, line):
        if current["lang"] != line["lang"] or len(current["text"]) > tuning.get("max_bubble_chars"):
            return False
        if line.get("gap") is not None and tuning.get("merge_sentences"):
            # From Anne.app, whose lines are whole sentences: short sentences of one speaker are gathered into one bubble until it holds
            # bubble_target_words; a long sentence stays whole. A new bubble starts when the speaker
            # changes (assign() handles "turn" and the other side speaking), after a long pause, or after a question and a pause (the
            # answer is most likely another person: voices are not told apart).
            if not ends_sentence(current["text"]) or line["text"][:1].islower():
                return True   # the app cut the sentence (a pause or its time limit): the rest always belongs to the same bubble
            if line["gap"] > tuning.get("bubble_gap_seconds"):
                return False
            qs = tuning.get("question_turn_seconds")
            if qs and current["text"].rstrip().endswith("?") and line["gap"] >= qs:
                return False
            # Decided from the open bubble alone, never from the length of the new sentence: the grey draft of a sentence that is
            # still being spoken must land in the same bubble as its final line (otherwise it would jump when the sentence grows).
            return len(current["text"].split()) < tuning.get("bubble_target_words")
        # Whisper often puts a full stop where it only paused: a small letter at the start continues the sentence.
        small_letter = tuning.get("small_letter_continues") and line["lang"] == "en" and line["text"][:1].islower()
        return small_letter or not ends_sentence(current["text"])
