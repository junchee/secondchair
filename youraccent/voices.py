"""The Kokoro voices yourAccent uses (Jun's choice, 2026-10-21).

bm_george is the target voice: the one Jun likes and wants to sound like, and the default reading
voice. All British voices and all American male voices are in the pool that the quiz mixes.
"""

TARGET = "bm_george"
BRITISH = ["bm_george", "bm_lewis", "bm_daniel", "bm_fable", "bf_emma", "bf_lily", "bf_isabella", "bf_alice"]
AMERICAN_MALE = ["am_michael", "am_liam", "am_echo", "am_adam", "am_eric", "am_fenrir", "am_onyx", "am_puck", "am_santa"]
ALL = BRITISH + AMERICAN_MALE


def lang_code(voice):
    """Kokoro wants 'b' for British voices and 'a' for American ones."""
    return "b" if voice.startswith("b") else "a"
