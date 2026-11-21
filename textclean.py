"""Small text clean-ups for lines from the recogniser, with no heavy imports (so tests can run anywhere)."""

import re

# A short sound label inside a line: "so [typing] we go", "(laughs)", "[BLANK_AUDIO]", "[ Silence ]", "（웃음）".
# Whisper and WhisperKit write sounds in brackets; real speech is never written that way. Up to 40 characters,
# no nesting, so a long bracketed remark is not cut away silently.
_LABEL = re.compile(r"[\[\(（【][^\]\)）】\[\(（【]{0,40}[\]\)）】]")


def strip_inline_labels(text):
    """Remove sound labels from a line. Returns (clean text, number of labels removed)."""
    found = len(_LABEL.findall(text))
    if not found:
        return text, 0
    return re.sub(r"\s+", " ", _LABEL.sub(" ", text)).strip(), found


def script_label(text):
    """For a line that is not English or Korean text: a short label of what it is written in ("ZH", "JA", "RU" ...), else "".
    The line still counts as "en" for translation (it goes to Korean); the label only tells the page and the bubble grouping."""
    counts = {"han": 0, "kana": 0, "cyr": 0, "arab": 0, "thai": 0, "other": 0}
    for ch in text:
        if not ch.isalpha():
            continue
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or code < 0x250:
            continue   # Hangul and Latin letters
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            counts["han"] += 1
        elif 0x3040 <= code <= 0x30FF:
            counts["kana"] += 1
        elif 0x0400 <= code <= 0x04FF:
            counts["cyr"] += 1
        elif 0x0600 <= code <= 0x06FF:
            counts["arab"] += 1
        elif 0x0E00 <= code <= 0x0E7F:
            counts["thai"] += 1
        else:
            counts["other"] += 1
    if sum(counts.values()) < max(1, len([c for c in text if c.isalpha()]) // 2):
        return ""   # mostly Latin or Hangul: an ordinary line with a foreign word or two
    if counts["kana"]:
        return "JA"
    top = max(counts, key=counts.get)
    return {"han": "ZH", "cyr": "RU", "arab": "AR", "thai": "TH", "other": "··"}[top]
