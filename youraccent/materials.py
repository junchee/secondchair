"""Scripts Jun wants to practise (lecture text and the like): saved as text, split into sentences."""

import io
import json
import os
import re
import threading
import uuid

from youraccent.sentences import split_sentences

MAX_CHARS = 200_000
ID = re.compile(r"m[0-9a-f]{12}")


def clean_text(text):
    """Join lines that were only wrapped (as in a PDF); keep blank lines as paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n\s*\n", text)
    joined = []
    for para in paragraphs:
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        out = ""
        for ln in lines:
            if out.endswith("-") and not out.endswith(" -"):
                out = out[:-1] + ln  # a word broken at the end of a line
            else:
                out = (out + " " + ln).strip()
        if out:
            joined.append(out)
    return "\n".join(joined)


def pdf_text(data):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


class Materials:
    def __init__(self, folder):
        self.folder = folder
        self.lock = threading.Lock()

    def _path(self, mid):
        return os.path.join(self.folder, mid + ".json")

    def create(self, title, text):
        title = " ".join(str(title).split())[:80] or "제목 없음"
        text = clean_text(str(text))[:MAX_CHARS]
        sentences = split_sentences(text)
        if not sentences:
            raise ValueError("no sentences")
        mid = "m" + uuid.uuid4().hex[:12]
        item = {"id": mid, "title": title, "sentences": sentences[:2000]}
        with self.lock:
            os.makedirs(self.folder, mode=0o700, exist_ok=True)
            tmp = self._path(mid) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path(mid))
        return item

    def get(self, mid):
        if not ID.fullmatch(str(mid)):
            return None
        try:
            with open(self._path(mid), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def listing(self):
        out = []
        try:
            names = sorted(os.listdir(self.folder))
        except OSError:
            return out
        for name in names:
            item = self.get(name[:-5]) if name.endswith(".json") else None
            if item:
                out.append({"id": item["id"], "title": item["title"], "count": len(item["sentences"])})
        return out

    def delete(self, mid):
        if not ID.fullmatch(str(mid)):
            return False
        try:
            os.remove(self._path(mid))
            return True
        except OSError:
            return False
