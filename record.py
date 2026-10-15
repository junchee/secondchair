"""Save each session's conversation in transcripts/.

    <start time>.jsonl  every line, translation and spoken event, written as it happens
                        (nothing is lost if secondchair is killed)
    <start time>.md     readable transcript, written when secondchair stops: the summary
                        (summary.py), then one entry per line with its final translation,
                        and what was spoken by voice

The folder is in .gitignore: transcripts stay on this Mac.
"""

import json
import os
import threading
import time

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")
KEPT = ("line", "translation", "spoken")
WHO = {"SYSTEM": "Them", "MIC": "Me"}


class Recorder:
    def __init__(self):
        os.makedirs(FOLDER, exist_ok=True)
        self.started = time.localtime()
        base = os.path.join(FOLDER, time.strftime("%Y-%m-%d_%H%M%S", self.started))
        self.jsonl_path = base + ".jsonl"
        self.md_path = base + ".md"
        self.lock = threading.Lock()
        self.file = open(self.jsonl_path, "a", encoding="utf-8")
        self.entries = []  # lines and spoken text, in order
        self.translations = {}  # line id -> latest translation

    def __call__(self, event):
        """An emit consumer: keep the events that belong in a transcript."""
        if event["type"] not in KEPT:
            return
        with self.lock:
            self.file.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.file.flush()
            if event["type"] == "translation":
                self.translations[event["id"]] = event["text"]
            else:
                self.entries.append(dict(event, time=event.get("time") or time.strftime("%H:%M:%S")))

    def plain_text(self):
        """The conversation as plain lines ("HH:MM:SS Them: ..."), originals only, for the summary."""
        with self.lock:
            lines = []
            for entry in self.entries:
                who = "Me (voice)" if entry["type"] == "spoken" else WHO[entry["source"]]
                lines.append(f"{entry['time']} {who}: {entry['text']}")
            return "\n".join(lines)

    def close(self, summary=None):
        """Write the readable transcript, with `summary` on top if given.
        Returns its path, or None if nothing was said."""
        with self.lock:
            self.file.close()
            if not self.entries:
                os.remove(self.jsonl_path)
                return None
            title = time.strftime("%Y-%m-%d %H:%M", self.started)
            out = [f"# Meeting transcript, {title}", ""]
            if summary:
                out += [summary.strip(), "", "## 전체 대화", ""]
            for entry in self.entries:
                if entry["type"] == "spoken":
                    out.append(f"**{entry['time']} Me (voice, English):** {entry['text']}")
                else:
                    out.append(f"**{entry['time']} {WHO[entry['source']]}:** {entry['text']}")
                    if entry["id"] in self.translations:
                        out.append(f"> {self.translations[entry['id']]}")
                out.append("")
            with open(self.md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            return self.md_path
