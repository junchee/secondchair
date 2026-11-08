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
