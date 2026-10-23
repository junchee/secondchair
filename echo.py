"""With speakers (no earphones) the microphone also records the meeting. A mic line that says what the
meeting just said, while the meeting was speaking, is that echo and is dropped."""
import re
import time
from collections import deque

WINDOW_SECONDS = 40      # how long a system line counts as "just said"
MATCH = 0.6              # share of the mic line's words that the meeting just said
MIN_WORDS = 2


def words(text):
    return re.findall(r"[a-z0-9']+", text.lower())


class EchoFilter:
    def __init__(self):
        self.recent = deque()  # (time, set of words) of the meeting's latest lines

    def reset(self):
        self.recent.clear()

    def note_system(self, text, now=None):
        now = time.time() if now is None else now
        self.recent.append((now, set(words(text))))
        while self.recent and now - self.recent[0][0] > WINDOW_SECONDS:
            self.recent.popleft()

    def is_echo(self, text, now=None):
        now = time.time() if now is None else now
        mine = words(text)
        if len(mine) < MIN_WORDS:
            return False
        heard = set()
        for at, system_words in self.recent:
            if now - at <= WINDOW_SECONDS:
                heard |= system_words
        return sum(w in heard for w in mine) / len(mine) >= MATCH
