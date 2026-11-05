"""Summarize a finished meeting with Qwen via OpenRouter (zero data retention, as in translate.py).

One call per meeting, so a larger model than the translator: quality matters more than cost here.
"""

import models
import tuning
from translate import Client

# the models for summary and Anne's answers are in models.py / config/models.json
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


ASK_PROMPT = f"""You are Anne, Jun's assistant during a meeting. Jun asks a question. "Them" are the other
participants in the transcript below, "Me" is Jun; it comes from speech recognition, may contain errors, and its
last line may be cut off.
- If the question is about what was said in this meeting, answer from the transcript only and begin the line with
  "📝 회의에서:". If the transcript does not contain the answer, say "📝 회의에서: 대화에서 찾을 수 없습니다" and,
  if useful, what is closest.
- If it is a general question (a term, a person, an organisation, a place, a concept), answer from your own
  knowledge and begin the line with "💡 일반 지식:". If you are not sure, or it may have changed recently, say so in
  a few words. Never invent facts, names or numbers.
- If both apply, write one line for each.
Answer in {LANGUAGE}, in at most four short sentences in total, so Jun can read it during the meeting."""


def answer(question, conversation, earlier=(), client=None):
    """Answer Jun's question from the conversation so far. `earlier` holds previous
    (question, answer) pairs so a follow-up like "그럼 걔는?" makes sense."""
    notes = "".join(f"\nPrevious question: {q}\nPrevious answer: {a}\n" for q, a in earlier)
    conversation = (conversation or "")[-tuning.get("ask_transcript_chars"):]   # the latest part: a cheaper request
    body = {
        "model": models.first("ask"),
        "messages": [
            {"role": "system", "content": ASK_PROMPT},
            {
                "role": "user",
                "content": f"Transcript so far:\n{conversation or '(nothing has been said yet)'}\n{notes}\nQuestion: {question}",
            },
        ],
        "temperature": 0.1,
        "max_tokens": tuning.get("ask_max_tokens"),
        "reasoning": {"enabled": False},
        "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
    }
    return (client or Client(timeout=60)).post(body)


def summarize(transcript, client=None):
    body = {
        "model": models.first("summary"),
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
