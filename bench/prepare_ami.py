"""Turn AMI word annotations into reference data for the speech test
(stage A of notes/bench_runbook_2026-11-05.md).

    python bench/prepare_ami.py --ami-dir bench/audio/ami [--meeting ES2004a ...] [--cut-seconds 300]

Input: AMI manual annotations 1.6.2, the `words/MEETING.SPEAKER.words.xml` files
(searched under --ami-dir). Output, in `--ami-dir/prepared/` (git ignores bench/audio):
  MEETING.ref.json      whole meeting: words, sentence ends, key items
  MEETING.cutNN.json    one piece of about --cut-seconds (cut at a sentence end): start/end second,
                        reference words with times, `ends`, `key` (indexes into the piece's own words)
  MEETING.cutNN.txt     the piece's reference text, one sentence per line
  manifest.json         the list of pieces

Choices (all meant to match what a speech recogniser is asked to write):
  - the speakers' files are merged by start time; where speakers overlap the order is by start time only;
  - fillers (uh, um, mm, hmm, mhm, uh-huh ...) and truncated words ("wh-") are dropped (`--keep-fillers` keeps them);
  - vocal sounds, gaps and comments are not words;
  - sentence end = a punctuation token . ? ! in the annotation, or the last word of a speaker's run with no end mark;
  - key items (heuristic): a number written with digits, a capitalised word that does not start a sentence
    (names, places), or a word of 10 or more letters (terms). `key` holds indexes into the words.

The XML layout is read from the AMI documentation and from memory of the files, not from a real file yet:
stage B checks it on the real download. Tags are matched by local name, so the nite: namespace does not matter.
"""

import argparse
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

FILLERS = {"uh", "um", "mm", "hmm", "mhm", "uh-huh", "uhhuh", "huh", "er", "erm", "ah", "eh", "mmm", "hm", "uh-uh"}
SENT_END_MARKS = {".", "?", "!"}
_NUMBER = re.compile(r"\d")


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def read_words_xml(path, speaker, keep_fillers=False):
    """Words of one speaker file: a list of dicts {w, start, end, spk, punc}. Punctuation tokens
    (punc="true") have no time of their own and are kept with punc=True so sentence ends can be found."""
    out = []
    for el in ET.parse(path).getroot().iter():
        if _local(el.tag) != "w":
            continue
        text = (el.text or "").strip()
        if not text:
            continue
        if el.get("punc") == "true" or text in SENT_END_MARKS or text in {",", ";", ":"}:
            out.append({"w": text, "start": None, "end": None, "spk": speaker, "punc": True})
            continue
        try:
            start, end = float(el.get("starttime")), float(el.get("endtime"))
        except (TypeError, ValueError):
            continue
        low = text.lower()
        if el.get("trunc") == "true" or text.endswith("-"):
            continue
        if low in FILLERS and not keep_fillers:
            continue
        out.append({"w": text, "start": start, "end": end, "spk": speaker, "punc": False})
    return out


def merge_speakers(per_speaker):
    """per_speaker: {speaker: [word dicts in order]} -> sentences sorted by start time.
    One speaker's words are cut into sentences at . ? ! (the mark stays with its sentence); words
    after the last mark form a sentence of their own. Each sentence is {start, spk, words}."""
    sentences = []
    for spk, tokens in per_speaker.items():
        cur = []
        for t in tokens:
            if t["punc"]:
                if t["w"] in SENT_END_MARKS and cur:
                    sentences.append({"start": cur[0]["start"], "spk": spk, "words": cur})
                    cur = []
                continue
            cur.append(t)
        if cur:
            sentences.append({"start": cur[0]["start"], "spk": spk, "words": cur})
    sentences.sort(key=lambda s: (s["start"], s["spk"]))
    return sentences


def build_meeting(per_speaker):
    """Merge the speakers; every sentence ends at its last word (an end mark, or the end of a
    speaker's run). Returns {"words": [{w,start,end,spk}], "ends": [idx], "key": [idx]}."""
    words, ends = [], []
    for s in merge_speakers(per_speaker):
        for t in s["words"]:
            words.append({"w": t["w"], "start": t["start"], "end": t["end"], "spk": t["spk"]})
        ends.append(len(words) - 1)
    return {"words": words, "ends": ends, "key": key_items(words, ends)}


def key_items(words, ends):
    """Heuristic key items: digits, capitalised words inside a sentence, long words (10+ letters)."""
    starts = {0} | {e + 1 for e in ends}
    key = []
    for i, w in enumerate(words):
        t = w["w"]
        letters = re.sub(r"[^A-Za-z]", "", t)
        if _NUMBER.search(t):
            key.append(i)
        elif i not in starts and t[:1].isupper() and t not in {"I", "I'm", "I'll", "I've", "I'd"} and len(letters) >= 2:
            key.append(i)
        elif len(letters) >= 10:
            key.append(i)
    return key


def make_cuts(meeting, cut_seconds=300.0):
    """Cut at the first sentence end after each cut_seconds. Returns a list of pieces
    {start, end, first, last (word indexes in the meeting), words, ends, key (relative indexes)}."""
    words, ends, key = meeting["words"], meeting["ends"], set(meeting["key"])
    if not words:
        return []
    cuts = []
    first = 0
    ends_sorted = sorted(ends)
    t0 = words[0]["start"]
    target = t0 + cut_seconds
    for e in ends_sorted:
        last = e
        if words[last]["end"] >= target or last == len(words) - 1:
            if last >= first:
                cuts.append(_piece(words, ends_sorted, key, first, last))
            first = last + 1
            target = words[first]["start"] + cut_seconds if first < len(words) else target
    if first < len(words):
        cuts.append(_piece(words, ends_sorted, key, first, len(words) - 1))
    return cuts


def _piece(words, ends, key, first, last):
    ws = words[first:last + 1]
    return {
        "start": ws[0]["start"], "end": ws[-1]["end"], "first": first, "last": last,
        "words": ws,
        "ends": [e - first for e in ends if first <= e <= last],
        "key": [k - first for k in sorted(key) if first <= k <= last],
    }


def piece_text(piece):
    """One sentence per line."""
    lines, start = [], 0
    for e in piece["ends"]:
        lines.append(" ".join(w["w"] for w in piece["words"][start:e + 1]))
        start = e + 1
    if start < len(piece["words"]):
        lines.append(" ".join(w["w"] for w in piece["words"][start:]))
    return "\n".join(lines) + "\n"


def find_meetings(ami_dir, wanted=None):
    """{meeting: {speaker: path}} from files named MEETING.SPEAKER.words.xml anywhere under ami_dir."""
    found = {}
    for path in glob.glob(os.path.join(ami_dir, "**", "*.words.xml"), recursive=True):
        parts = os.path.basename(path).split(".")
        if len(parts) < 4:
            continue
        meeting, speaker = parts[0], parts[1]
        if wanted and meeting not in wanted:
            continue
        found.setdefault(meeting, {})[speaker] = path
    return found


def prepare(ami_dir, wanted=None, cut_seconds=300.0, keep_fillers=False):
    meetings = find_meetings(ami_dir, wanted)
    if not meetings:
        raise SystemExit(f"no *.words.xml files under {ami_dir}")
    out_dir = os.path.join(ami_dir, "prepared")
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    for name in sorted(meetings):
        per_speaker = {spk: read_words_xml(p, spk, keep_fillers) for spk, p in sorted(meetings[name].items())}
        meeting = build_meeting(per_speaker)
        with open(os.path.join(out_dir, f"{name}.ref.json"), "w") as f:
            json.dump({"meeting": name, **meeting}, f)
        for n, piece in enumerate(make_cuts(meeting, cut_seconds), 1):
            stem = f"{name}.cut{n:02d}"
            with open(os.path.join(out_dir, stem + ".json"), "w") as f:
                json.dump({"meeting": name, "cut": n, **piece}, f)
            with open(os.path.join(out_dir, stem + ".txt"), "w") as f:
                f.write(piece_text(piece))
            manifest.append({"id": stem, "meeting": name, "start": piece["start"], "end": piece["end"],
                             "words": len(piece["words"]), "sentences": len(piece["ends"]), "key": len(piece["key"])})
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ami-dir", required=True)
    p.add_argument("--meeting", action="append")
    p.add_argument("--cut-seconds", type=float, default=300.0)
    p.add_argument("--keep-fillers", action="store_true")
    args = p.parse_args()
    manifest = prepare(args.ami_dir, args.meeting, args.cut_seconds, args.keep_fillers)
    print(f"{'piece':18} {'start':>8} {'end':>8} {'words':>6} {'sent':>5} {'key':>4}")
    for m in manifest:
        print(f"{m['id']:18} {m['start']:8.1f} {m['end']:8.1f} {m['words']:6d} {m['sentences']:5d} {m['key']:4d}")
    print(f"{len(manifest)} pieces in {os.path.join(args.ami_dir, 'prepared')}")


if __name__ == "__main__":
    sys.exit(main())
