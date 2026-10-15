"""Save each session's conversation in transcripts/.

    <start time>.jsonl  every line, translation, spoken text and mid-meeting summary, written
                        as it happens (nothing is lost if secondchair is killed)
    <start time>.md     readable transcript, written when secondchair stops: the final summary
                        (summary.py), then one entry per line with its final translation,
                        what was spoken by voice, and each mid-meeting summary where it was made

Text Jun typed to get a translation is not saved: it was not said in the meeting.
The folder is in .gitignore: transcripts stay on this Mac.
"""

import json
import os
import re
import threading
import time

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")
KEPT = ("line", "translation", "spoken", "summary")
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
        self.entries = []  # lines, spoken text and mid-meeting summaries, in order
        self.translations = {}  # line id -> latest translation

    def __call__(self, event):
        """An emit consumer: keep the events that belong in a transcript."""
        if event["type"] not in KEPT or (event["type"] == "summary" and (event["final"] or not event["text"])):
            return  # the final summary goes on top of the .md (close), not in the stream
        with self.lock:
            self.file.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.file.flush()
            if event["type"] == "translation":
                self.translations[event["id"]] = event["text"]
            else:
                self.entries.append(dict(event, time=event.get("time") or time.strftime("%H:%M:%S")))

    def plain_text(self, last=None):
        """The conversation as plain lines ("HH:MM:SS Them: ..."), originals only.
        Summaries are left out. `last` keeps only the latest lines."""
        with self.lock:
            lines = []
            for entry in self.entries:
                if entry["type"] == "summary":
                    continue
                who = "Me (voice)" if entry["type"] == "spoken" else WHO[entry["source"]]
                lines.append(f"{entry['time']} {who}: {entry['text']}")
            return "\n".join(lines[-last:] if last else lines)

    def close(self, summary=None):
        """Write the readable transcript, with `summary` on top if given.
        Returns its path, or None if nothing was said."""
        with self.lock:
            self.file.close()
            if not any(entry["type"] != "summary" for entry in self.entries):
                os.remove(self.jsonl_path)
                return None
            title = time.strftime("%Y-%m-%d %H:%M", self.started)
            out = [f"# Meeting transcript, {title}", ""]
            if summary:
                out += [summary.strip(), "", "## 전체 대화", ""]
            for entry in self.entries:
                if entry["type"] == "summary":
                    # Nest its "## ..." sections under this heading.
                    body = re.sub(r"^##\s", "#### ", entry["text"].strip(), flags=re.M)
                    out += [f"### 중간 요약 ({entry['time']})", "", body]
                elif entry["type"] == "spoken":
                    out.append(f"**{entry['time']} Me (voice, English):** {entry['text']}")
                else:
                    out.append(f"**{entry['time']} {WHO[entry['source']]}:** {entry['text']}")
                    if entry["id"] in self.translations:
                        out.append(f"> {self.translations[entry['id']]}")
                out.append("")
            with open(self.md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            return self.md_path
