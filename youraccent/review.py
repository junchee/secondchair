"""Words and sentences to come back to.

A word that was read wrong (or not heard, or doubtful) is saved with the sentence it was in. It is
due again the same day, and each time it is read right in a later practice it moves on: due again
after 1 day, then 3 days, and after three right readings in a row it graduates and leaves the list.
A wrong reading puts it back to the start. A right reading counts once a day at most. Jun can also
save any word or sentence by hand. Text only, kept in one JSON file; audio is never stored here.
"""

import datetime
import json
import os
import re
import threading

from youraccent.judge import SKIP_DOUBT

INTERVALS = [1, 3]  # days until due again after the 1st and 2nd right reading in a row
GRADUATE_AT = 3
MAX_EXAMPLES = 3


def today_str():
    return datetime.date.today().isoformat()


def item_id(kind, text):
    return f"{kind}:{re.sub(r'[^a-z0-9 ]', '', text.lower()).strip()[:80]}"


class Review:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.items = {}
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("items"), dict):
                self.items = loaded["items"]
        except (OSError, ValueError):
            pass

    def _new(self, kind, text, today):
        return {"id": item_id(kind, text), "kind": kind, "text": text, "examples": [], "misses": 0,
                "streak": 0, "due": today, "graduated": False, "last_ok": None, "heard_as": ""}

    def update_from_attempt(self, sentence, rows, today=None):
        """Apply one reading of `sentence`: rows are the judged words."""
        today = today or today_str()
        with self.lock:
            for r in rows:
                key = item_id("word", r["word"])
                if not re.sub(r"[^a-z0-9]", "", r["word"].lower()) or r["word"].lower() in SKIP_DOUBT:
                    continue  # small function words are often misheard ("in" as "and"): not worth a review
                item = self.items.get(key)
                if r["status"] in ("wrong", "missed", "doubt"):
                    if item is None:
                        item = self.items[key] = self._new("word", r["word"].lower(), today)
                    item.update(misses=item["misses"] + 1, streak=0, due=today, graduated=False,
                                heard_as=r["heard_as"])
                    examples = [e for e in item["examples"] if e != sentence] + [sentence]
                    item["examples"] = examples[-MAX_EXAMPLES:]
                elif item is not None and not item["graduated"] and item["last_ok"] != today:
                    item["streak"] += 1
                    item["last_ok"] = today
                    if item["streak"] >= GRADUATE_AT:
                        item["graduated"] = True
                    else:
                        days = INTERVALS[min(item["streak"] - 1, len(INTERVALS) - 1)]
                        item["due"] = (datetime.date.fromisoformat(today) + datetime.timedelta(days=days)).isoformat()
            self._save()

    def save_by_hand(self, kind, text, today=None):
        text = " ".join(text.split())
        if kind not in ("word", "sentence") or not text or len(text) > 400:
            raise ValueError("bad item")
        with self.lock:
            key = item_id(kind, text)
            item = self.items.get(key) or self._new(kind, text.lower() if kind == "word" else text, today or today_str())
            item.update(graduated=False, due=today or today_str(), streak=0)
            self.items[key] = item
            self._save()
            return dict(item)

    def delete(self, key):
        with self.lock:
            removed = self.items.pop(key, None) is not None
            if removed:
                self._save()
            return removed

    def listing(self, today=None):
        """All items that are still in practice, with whether each is due now, most missed first."""
        today = today or today_str()
        with self.lock:
            out = [dict(i, is_due=i["due"] <= today) for i in self.items.values() if not i["graduated"]]
            graduated = sum(1 for i in self.items.values() if i["graduated"])
        out.sort(key=lambda i: (not i["is_due"], -i["misses"], i["text"]))
        return {"items": out, "graduated": graduated, "today": today}

    def _save(self):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"items": self.items}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
