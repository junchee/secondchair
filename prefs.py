"""Choices that outlive one run of the program, kept in user_settings.json (not in git).

Settings (line lengths, mic filter, translation on/off), the voice, the monitor and its volume.
A missing, damaged or unreadable file just means "use the defaults".
"""

import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_settings.json")


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(**values):
    """Add or change some values; the others in the file stay as they are."""
    data = load()
    data.update(values)
    temporary = PATH + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temporary, PATH)  # never leaves a half-written file
    except OSError:
        pass  # the change still applies until the program stops
