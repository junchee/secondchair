# Translation judge, English -> Korean (one sentence), v2 2026-11-06

v2 changes severity: it now depends on whether the speaker's main claim is changed, not on the error type (after Jun's check of 20 samples; v1 is kept in `translation_judge_v1.md`; regression cases in `judge_regression_cases.json`).
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
- Saying out loud what the earlier sentences make clear: the thing "it" or "them" refers to, the unit of a price already given.
- A fragment translated as a fragment. A backchannel ("Yeah", "Okay", "Mm-hmm") given as any short reply (네, 예, 음, 응, 알겠어요, 좋아요), or left empty, unless it answers a question in the earlier sentences.

Error types:
- `omission`: part of the meaning is missing.
- `addition`: meaning that is not in the English sentence: an explanation, reason or fact the speaker did not give, a different item taken from the earlier sentences, a completed fragment.
- `wrong_meaning`: said differently from the English (wrong word sense, a literal rendering of an idiom or phrasal verb, wrong relation, wrong tone of a claim such as "maybe" made certain).
- `wrong_name_or_number`: a name, number, amount, unit, currency, time or date that differs from the English.

Severity. First find the speaker's main claim: what the sentence says happens or should happen, who does it to what, whether, how many, and any reason, condition or deadline the speaker states. Details are: one item in a list of several, a manner word, a hedge, a side remark. Then rate each error by what it does to the main claim, not by its type. An addition is minor when the main claim stays intact, and major only when it adds a fact a reader could act on (a number, a person, a date, a decision or a commitment).
- `minor`: the main claim reaches the reader intact. Examples: "I think it's cheaper" -> "더 싸요" (hedge lost); "it can play music, show photos or set alarms" -> "음악을 틀거나 사진을 편집하거나 알람을…" (one list item changed); "she read the report quickly" -> "꼼꼼히 읽었어요" (manner changed); "the app is faster now" -> "새 서버 덕분에 앱이 더 빨라졌어요" (an explanation added that the speaker did not give).
- `major`: the main claim is unclear, empty or partly missing, but not replaced by a definite false one. Examples: "can you pick up the slides?" -> "슬라이드를 집어 줄래요?" (literal: the reader gets an odd, empty idea instead of "fetch"); "we should test it before Friday's demo" -> "테스트해야 해요" (the stated deadline is gone); an added number, person, date or decision ("let's meet again" -> "월요일에 다시 만나요").
- `critical`: the reader would take away a definite false claim and could believe or act on it. Always critical: a name, number, amount, currency or time that the English gives, said wrongly; negation flipped ("we can't ship it" -> "출시할 수 있어요"); who did what swapped ("Tom replaced Anna" -> "안나가 톰을 대신했어요"); a word in the main claim (or in the reason the speaker gives) replaced by one with another sense so that the claim becomes a different, plausible one ("we lend the tools to students" -> "학생들에게 도구를 팔아요"); a backchannel answer turned around ("No." -> "네."); an empty candidate for a sentence with content.

`meaning`:
- `right`: no major or critical error (minor errors allowed).
- `partly`: at least one major error, no critical one; the main point survives.
- `wrong`: any critical error, or the main point is lost.

`critical`: one short string per critical error, for example "15유로 for twenty five Euros". Empty list if none. It must match the critical items in `errors`.
`span`: the words from the candidate; for an omission, the missing English words.

Answer with one JSON object, nothing else (no code fence):
{"meaning": "right" | "partly" | "wrong", "critical": [], "errors": [{"type": "...", "severity": "...", "span": "...", "note": "..."}], "comment": "<one short sentence>"}
