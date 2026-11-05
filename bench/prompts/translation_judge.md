# Translation judge, English -> Korean (one sentence)

Run with: Claude Sonnet, temperature 0 (Haiku only after it agrees with Sonnet on a checked sample). One call per sentence and candidate.
Placeholders: `{{previous}}`, `{{source_en}}`, `{{reference_ko}}`, `{{candidate_ko}}`, `{{key_items}}` (may be empty).
Method: an error-span judgment after GEMBA-MQM, cut down to four error types. Everything below the line is the prompt.

---

You check the Korean translation of one sentence from a live English meeting. A Korean reader relies on this translation to follow the meeting. Judge meaning only: does the reader understand what the speaker said? Do not judge style.

Earlier sentences (context only):
{{previous}}

English sentence (what the speaker really said):
{{source_en}}

Reference Korean (a correct translation, one of many possible):
{{reference_ko}}

Candidate Korean (to judge):
{{candidate_ko}}

Key items (names, numbers, terms; may be empty; a heuristic list, ignore ordinary words in it):
{{key_items}}

Compare the candidate with the English sentence. Use the reference to see one correct reading, not as the only right wording. The candidate may come from a speech recogniser's text, not from this exact English: any difference in meaning from the English is an error, whatever its cause.

Not errors:
- Other wording, word order, register or politeness level (합니다, 해요, 반말), 그녀/그분, Hangul or Latin spelling of a name (세라/사라/Sarah), digits or Korean number words, "…" at the end.
- Dropped fillers, repetitions and false starts; dropped "you know", "I mean", "like".
- A fragment translated as a fragment. A backchannel ("Yeah", "Okay", "Mm-hmm") given as any short reply (네, 예, 음, 응, 알겠어요, 좋아요), or left empty, unless it answers a question in the earlier sentences.

Error types:
- `omission`: part of the meaning is missing.
- `addition`: meaning that is not in the English sentence (also words taken from the earlier sentences, or a completed fragment).
- `wrong_meaning`: said differently from the English (wrong word sense, wrong relation, wrong tone of a claim such as "maybe" made certain).
- `wrong_name_or_number`: a name, number, amount, unit, currency, time or date that differs from the English.

Severity:
- `minor`: the reader still gets the point. Examples: "I think it's cheaper" -> "더 싸요" (hedge lost); "red, blue or green" -> "빨강이나 파랑" (one example of a list dropped).
- `major`: the reader misses or misreads part of the point. Examples: "we should test it before Friday's demo" -> "테스트해야 해요" (the deadline is gone); "it saves battery" -> "배터리를 확인해요" (wrong verb); a sentence clause invented.
- `critical`: the reader would take away a false fact or act on it. Always critical: a wrong name, number, amount, currency or time; negation flipped ("we can't ship it" -> "출시할 수 있어요"); who did what swapped ("Tom replaced Anna" -> "안나가 톰을 대신했어요"); a backchannel answer turned around ("No." -> "네."); an empty candidate for a sentence with content.

`meaning`:
- `right`: no major or critical error (minor errors allowed).
- `partly`: at least one major error, no critical one; the main point survives.
- `wrong`: any critical error, or the main point is lost.

`critical`: one short string per critical error, for example "15유로 for twenty five Euros". Empty list if none. It must match the critical items in `errors`.
`span`: the words from the candidate; for an omission, the missing English words.

Answer with one JSON object, nothing else (no code fence):
{"meaning": "right" | "partly" | "wrong", "critical": [], "errors": [{"type": "...", "severity": "...", "span": "...", "note": "..."}], "comment": "<one short sentence>"}
