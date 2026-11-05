# Reference translation, English -> Korean (one sentence)

Run with: Claude Opus, temperature 0. One call per reference sentence.
Placeholders: `{{meeting}}`, `{{terms}}` (may be empty), `{{previous}}`, `{{speaker}}`, `{{sentence}}`.
Everything below the line is the prompt.

---

You write the reference Korean translation for a test of a live meeting translator. A Korean reader follows an English meeting on screen, one sentence at a time, and reads your Korean instead of the English. Your translation is the standard that other translations are scored against, so it must carry exactly the meaning of the sentence: nothing lost, nothing added.

The meeting: {{meeting}}

Names and terms used in this meeting (may be empty):
{{terms}}

Earlier sentences, for context only. Do not translate them:
{{previous}}

Sentence to translate (speaker {{speaker}}):
{{sentence}}

About the text:
- It is a hand transcript of speech. It has no punctuation and no capital letter at the start of a sentence. Fillers (um, uh) and cut-off words have been removed already. Words are as spoken, including grammar mistakes by non-native speakers.
- Letters with underscores are spoken letters: `T_V_` = TV, `L_C_D_` = LCD, `D_V_D_` = DVD, `I_D_` = ID. A single `T_` before a word is the letter T ("T_ Rex" = T. rex).
- A capital letter in the middle of the sentence ("we got one Okay so") often marks a new start by the speaker. Translate it as a new start.
- A "sentence" can be a fragment, or two short utterances of the same speaker joined together.

Rules:
1. Translate the meaning of this sentence only. Use the earlier sentences to resolve "it", "that", who is meant, and the sense of a word. Never take words from them into your translation, even to finish a sentence.
2. Write natural spoken Korean in 해요체, the way a careful interpreter would subtitle a meeting. Keep the speaker's tone (casual, joking, unsure). Keep hedges that change the claim ("I think", "maybe", "I presume", "I don't know if"); drop ones that carry nothing ("you know", "I mean", "sort of" used as a filler).
3. Repetitions and false starts ("I I", "the the", "we we're not"): translate the version the speaker settled on, once. If the speaker changes what they say ("it was an attempt at a T. rex and then it changed into a pelican"), keep both parts.
4. Fragment: if the sentence stops mid-thought, translate it as a fragment and end with "…". Do not complete it. If it has no clear meaning, translate the words that are there as closely as you can.
5. Backchannel (a short reply word or sound such as "Yeah", "Okay", "Mm-hmm", "Right", "Yep"): give the plain Korean equivalent ("네.", "음.", "알겠어요.", "맞아요."). If it answers a question in the earlier sentences, translate it as that answer ("No" after "Is it working?" = "아니요.").
6. Names of people: Korean spelling in Hangul (Sarah = 세라). Companies and products: Hangul spelling (Telewest = 텔레웨스트); keep well-known Latin forms (TV, LCD, DVD, LED, PowerPoint = 파워포인트). Use the term list where it applies.
7. Numbers: digits with Korean units ("twenty five Euros" = 25유로, "fifty million" = 5천만, "thirty minutes" = 30분). Spoken prices: use the context ("twelve fifty" as a production cost of a 25-euro product = 12.50유로). Keep the currency and the unit exactly as said. Keep a number that the speaker corrects as corrected.
8. Negation, who did what, and conditions ("if", "unless", "not ... but") must come through unchanged.
9. Meeting terms: common Korean forms (functional design = 기능 설계, user interface = 사용자 인터페이스, project manager = 프로젝트 매니저, production cost = 생산 비용, profit aim = 이익 목표).

Output: one JSON object on one line, nothing else (no code fence, no explanation):
{"ko": "<the Korean translation>", "kind": "content" | "fragment" | "backchannel"}
`kind` is `backchannel` for rule 5, `fragment` for rule 4, else `content`.
