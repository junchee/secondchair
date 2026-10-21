"""The Kokoro voices yourAccent uses (Jun's choice, 2026-10-21).

bm_lewis is the target voice: the one that explains each pair and replays the two words after a
miss. Jun hears it very clearly. All British voices and all American male voices are in the pool
that the quiz mixes, except bm_george: Jun liked it, but on trying the training he found it not
clear enough for pronunciation practice (Whisper had also heard its "right" as "light").
"""

TARGET = "bm_lewis"
BRITISH = ["bm_lewis", "bm_fable", "bm_daniel", "bf_emma", "bf_lily", "bf_isabella", "bf_alice"]
AMERICAN_MALE = ["am_michael", "am_liam", "am_echo", "am_adam", "am_eric", "am_fenrir", "am_onyx", "am_puck", "am_santa"]
ALL = BRITISH + AMERICAN_MALE


def lang_code(voice):
    """Kokoro wants 'b' for British voices and 'a' for American ones."""
    return "b" if voice.startswith("b") else "a"
