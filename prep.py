"""배경지식 (background) for a meeting: Jun writes or pastes what the meeting is about. When he saves it, a
stronger model reads it once and returns a one-line topic and the key terms with their Korean forms, chosen
for this meeting. Only these go further: the topic and the terms that occur in a line go with its translation,
and the terms go to Whisper as a hint. The background text itself is kept for Jun, not sent with each line."""
import json

import translate

DIGEST_MODEL = "anthropic/claude-haiku-5.5"  # once per save: worth a better model than the per-line one
MAX_TERMS = 40
WHISPER_PROMPT_CHARS = 500


def clean_terms(raw):
    """A list of {"en", "ko"} from whatever came in: bad entries dropped, duplicates merged, at most MAX_TERMS."""
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        en, ko = str(item.get("en", "")).strip()[:80], str(item.get("ko", "")).strip()[:80]
        if en and en.lower() not in seen:
            seen.add(en.lower())
            out.append({"en": en, "ko": ko})
    return out[:MAX_TERMS]


def whisper_prompt(topic, terms):
    """The text that starts Whisper's prompt: the topic and the meeting's names and terms."""
    parts = []
    if topic.strip():
        parts.append(topic.strip().rstrip(".") + ".")
    if terms:
        parts.append("Terms: " + ", ".join(t["en"] for t in terms) + ".")
    return " ".join(parts)[:WHISPER_PROMPT_CHARS]


def digest(background, client=None):
    """(topic, terms) from the background text: one line about the meeting, and the key terms only."""
    client = client or translate.Client(timeout=60)
    body = {
        "model": DIGEST_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You prepare a meeting for live English <-> Korean transcription and translation. From the "
                "background text, write (1) the topic of the meeting in one short line, in English, and (2) a glossary of "
                f"at most {MAX_TERMS} key terms: names of people, places and organisations, specialist terms, acronyms, and "
                "words that have a special meaning in this meeting. Leave out everyday words a translator gets right "
                "anyway. For each term give the English form as it is spoken or written and the Korean form that fits "
                "this meeting's context (not the general dictionary sense; for a name the usual Korean spelling, for an "
                "acronym Korean speakers keep, the acronym itself). Reply with JSON only: "
                '{"topic": "...", "terms": [{"en": "...", "ko": "..."}]}',
            },
            {"role": "user", "content": background.strip()},
        ],
        "temperature": 0,
        "max_tokens": 2000,
        "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
    }
    answer = client.post(body)
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("the model did not return the expected answer")
    data = json.loads(answer[start : end + 1])
    return str(data.get("topic", "")).strip()[:200], clean_terms(data.get("terms"))
