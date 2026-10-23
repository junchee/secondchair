"""Preparing a meeting: a sentence about it, optional documents, and a list of names and terms with their
Korean forms. The list goes to Whisper (as the start of its prompt) and to the translation prompt."""
import base64
import io
import json
import re

import translate

MAX_TERMS = 60
MAX_TEXT_CHARS = 14000        # of all documents together, sent to the model
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


def whisper_prompt(context, terms):
    """The text that starts Whisper's prompt: what the meeting is about and its names and terms."""
    parts = []  # the terms first: a long background text must not push them out of the short prompt
    if terms:
        parts.append("Terms: " + ", ".join(t["en"] for t in terms) + ".")
    if context.strip():
        parts.append(" ".join(context.split()))
    return " ".join(parts)[:WHISPER_PROMPT_CHARS]


def pdf_text(data):
    """Text of a PDF (bytes). Needs the optional pypdf; raises RuntimeError with what to do if it is missing."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("PDF reading needs one more package: run  .venv/bin/pip install pypdf  and start again")
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def documents_text(files):
    """files: [{"name", "text"} or {"name", "base64"}] -> one text (cut to MAX_TEXT_CHARS, shares equal)."""
    texts = []
    for item in files[:10]:
        if "base64" in item:
            data = base64.b64decode(item["base64"])
            text = pdf_text(data) if str(item.get("name", "")).lower().endswith(".pdf") else data.decode("utf-8", "replace")
        else:
            text = str(item.get("text", ""))
        texts.append(re.sub(r"[ \t]+", " ", text).strip())
    texts = [t for t in texts if t]
    if not texts:
        return ""
    share = MAX_TEXT_CHARS // len(texts)
    return "\n\n".join(t[:share] for t in texts)


def find_terms(context, documents, client=None):
    """Ask the model for names and terms (with Korean forms) that this meeting is likely to need."""
    client = client or translate.Client(timeout=30)
    body = {
        "model": translate.BUBBLE_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You prepare a glossary for the live English-to-Korean transcription and translation of a meeting. "
                f"From the meeting description and the documents, list up to {MAX_TERMS} names of people and places, "
                "organisations, specialist terms, acronyms and phrases that a speech recogniser might mishear or a "
                "translator might render wrongly. For each give the English form exactly as it is spoken or written "
                'and its natural Korean rendering (for a name or an acronym the usual Korean form, or the same text '
                'if Korean speakers keep it). Reply with JSON only: [{"en": "...", "ko": "..."}]',
            },
            {"role": "user", "content": f"Meeting: {context.strip() or '(not described)'}\n\nDocuments:\n{documents or '(none)'}"},
        ],
        "temperature": 0,
        "max_tokens": 2500,
        "reasoning": {"enabled": False},
        "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
    }
    answer = client.post(body)
    start, end = answer.find("["), answer.rfind("]")
    if start < 0 or end < start:
        raise RuntimeError("the model did not return a list")
    return clean_terms(json.loads(answer[start : end + 1]))
