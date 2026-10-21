"""What Jun has practised: how many answers, how many right, which words got mixed up.

Kept as text in one JSON file in yourAccent's own folder (never in the repo, never sent anywhere).
Audio is not stored here.
"""

import datetime
import json
import os
import threading

RECENT = 10  # a pair is passed when this many of the latest answers hold PASS_AT right ones
PASS_AT = 9


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"pairs": {}}
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("pairs"), dict):
                self.data = loaded
        except (OSError, ValueError):
            pass  # no file yet, or a damaged one: start empty

    def _pair(self, pair_id):
        return self.data["pairs"].setdefault(
            pair_id,
            {"trials": 0, "correct": 0, "recent": [], "passed": False, "passed_at": None, "confusions": {}},
        )

    def get(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def record(self, pair_id, played, chosen, voice):
        """One answer. Returns the pair's progress and whether this answer made it pass."""
        right = played == chosen
        with self.lock:
            pair = self._pair(pair_id)
            pair["trials"] += 1
            pair["correct"] += int(right)
            pair["recent"] = (pair["recent"] + [int(right)])[-RECENT:]
            if not right:
                key = f"{played}>{chosen}"  # played this word, heard it as the other one
                pair["confusions"][key] = pair["confusions"].get(key, 0) + 1
            just_passed = False
            if not pair["passed"] and len(pair["recent"]) == RECENT and sum(pair["recent"]) >= PASS_AT:
                pair["passed"] = just_passed = True
                pair["passed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            self._save()
            return {**json.loads(json.dumps(pair)), "just_passed": just_passed}

    def _save(self):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
