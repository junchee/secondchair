"""Sentences for the yourAccent first test, and a splitter for the user's own script."""

import re

# (sentence, target words, the sounds these words test). Each target has a near twin in
# English, so a wrong sound turns it into a different real word.
TRAPS = [
    ("Please turn on the light on the right side.", ("light", "right"), "L / R"),
    ("I think the sink in the kitchen is broken.", ("think", "sink"), "th / s"),
    ("Every berry in this bowl is very sweet.", ("berry", "very"), "B / V"),
    ("The sheep are standing next to the ship.", ("sheep", "ship"), "long ee / short i"),
    ("I want a cup of coffee and a copy of the report.", ("coffee", "copy"), "F / P"),
    ("The thief took three thick books.", ("thief", "three", "thick"), "th / f / s"),
    ("The vine grows behind the wine shop.", ("vine", "wine"), "V / W"),
    ("They live in a lovely village near the river.", ("lovely", "village", "river"), "L / R / V"),
]


def split_sentences(text):
    """Split a script into sentences at . ? ! and at line breaks. Very short pieces are dropped."""
    pieces = re.split(r"(?<=[.!?])\s+|\n+", text)
    sentences = [" ".join(piece.split()) for piece in pieces]
    return [s for s in sentences if len(s.split()) >= 3]
