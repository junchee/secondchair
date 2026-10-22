"""Which lines belong to one bubble: a line cut in the middle of a sentence (short pause, longest-line
setting, or a full stop Whisper put on a mere pause) continues its speaker's open bubble.

A bubble is named by the id of its first line; every line event carries it as "bubble".
"""
from translate import ends_sentence

MAX_BUBBLE_CHARS = 500


class Grouper:
    def __init__(self):
        self.reset()

    def reset(self):
        self.open = {}  # source -> {"id": first line id, "text": text so far, "lang": ...}
        self.last_source = None

    def assign(self, line):
        """Return the bubble id for this line (a line event, with its id already set)."""
        source = line["source"]
        if self.last_source not in (None, source):
            self.open.pop(self.last_source, None)  # the other side spoke in between: that bubble is closed
        self.last_source = source
        current = self.open.get(source)
        if current and self._continues(current, line):
            current["text"] += " " + line["text"]
            return current["id"]
        self.open[source] = {"id": line["id"], "text": line["text"], "lang": line["lang"]}
        return line["id"]

    @staticmethod
    def _continues(current, line):
        if current["lang"] != line["lang"] or len(current["text"]) > MAX_BUBBLE_CHARS:
            return False
        # Whisper often puts a full stop where it only paused: a small letter at the start continues the sentence.
        small_letter = line["lang"] == "en" and line["text"][:1].islower()
        return small_letter or not ends_sentence(current["text"])
