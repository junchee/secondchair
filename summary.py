"""Summarize a finished meeting with Qwen via OpenRouter (zero data retention, as in translate.py).

One call per meeting, so a larger model than the translator: quality matters more than cost here.
"""

from translate import Client

MODEL = "qwen/qwen3.5-35b-a3b"
LANGUAGE = "Korean"

PROMPT = f"""You summarize a meeting transcript for Jun. "Them" are the other participants, "Me" is Jun.
The transcript comes from speech recognition and may contain errors; do not invent anything that
is not in it. Write in {LANGUAGE}, in Markdown, with exactly these sections:

## 핵심 요약
3 to 5 bullet points.
## 결정 사항
## 할 일
Who does what, and by when if it was said.
## 열린 질문
Questions or issues left open.

Write "없음" under a section that has nothing."""


def summarize(transcript, client=None):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": transcript},
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
        "reasoning": {"enabled": False},
        "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
    }
    return (client or Client(timeout=90)).post(body)
