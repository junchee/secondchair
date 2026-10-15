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


ASK_PROMPT = f"""You answer Jun's questions about a meeting that is going on, using only the transcript
below. "Them" are the other participants, "Me" is Jun. The transcript comes from speech
recognition and may contain errors, and its last line may be cut off. Answer in {LANGUAGE}, in one to
four short sentences, so Jun can read it during the meeting. If the transcript does not contain
the answer, say "대화에서 찾을 수 없습니다" and, if useful, what is closest. Never invent facts, names or
numbers."""


def answer(question, conversation, earlier=(), client=None):
    """Answer Jun's question from the conversation so far. `earlier` holds previous
    (question, answer) pairs so a follow-up like "그럼 걔는?" makes sense."""
    notes = "".join(f"\nPrevious question: {q}\nPrevious answer: {a}\n" for q, a in earlier)
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": ASK_PROMPT},
            {
                "role": "user",
                "content": f"Transcript so far:\n{conversation or '(nothing has been said yet)'}\n{notes}\nQuestion: {question}",
            },
        ],
        "temperature": 0.1,
        "max_tokens": 400,
        "reasoning": {"enabled": False},
        "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
    }
    return (client or Client(timeout=60)).post(body)


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
