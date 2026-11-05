# Stage C report (2026-11-05)

Ran by an Opus subagent. No paid service was called: the agent wrote the sample translations and verdicts itself. The prompts have NOT been run by the tests yet.

## What exists
- `bench/prompts/reference_translation.md` (Opus): one JSON line `{"ko", "kind": content|fragment|backchannel}`.
- `bench/prompts/translation_judge.md` (Sonnet, temperature 0): one JSON line `meaning` right|partly|wrong, `critical`, `errors` (omission, addition, wrong_meaning, wrong_name_or_number; minor|major|critical), `comment`. Method after GEMBA-MQM.
- `bench/prompts/README.md`: which model runs what.
- Local only (git ignores `bench/results/`, AMI text): `bench/results/C/samples_for_jun.md` (20 samples, Korean notes, 8 planted errors listed at the end under "정답(마지막에 볼 것)") and `bench/results/C/prompt_check.md` (notes for stage D).

## Samples
C01-C20 spread over ES2004a (9), IS1009a (6), TS3003a (4+1 cut05). Planted errors in C05, C08, C09, C11, C14, C15, C17, C20. Each sample is one sentence.

## Decisions Jun may disagree with
1. Backchannels: any short reply is right, and so is an empty output, unless it answers a question. 239 of 871 sentences (27%) are bare backchannels, so stage D reports `Meaning` with and without them.
2. Severity: a wrong name, number, currency or time, a flipped negation or swapped who-did-what is critical (then `meaning` = wrong). A dropped list item or lost hedge is minor (`meaning` stays right). Jun's answers on C07, C11, C12 show whether minor is too strict or too loose.
3. Register and names: references use 해요체; the judge ignores register. Names in Hangul (Sarah = 세라), TV/LCD/DVD in Latin letters; the judge accepts any spelling.
4. Context: two earlier sentences in piece order (may be other speakers); overlap is not special; no following sentence.

## AMI data problems found
- Some sentence units join two utterances of one speaker across a long gap (ES2004a.cut03 S06 "So then Mm-hmm", 636-688 s; ES2004a.cut02 S19; IS1009a.cut02 S93; TS3003a.cut05 S54). A mid-sentence capital ("Yeah", "Okay", "Gonna") usually marks the restart, and the key-item heuristic flags those words: stage D filters them.
- Spoken letters are written `T_V_`, `L_C_D_`, `D_V_D_`, `I_D_`, `T_ Rex`: turn them into TV, LCD ... before any system sees them.
- A few mishearings or truncations ("ordinary mote controls", "Divides us"), one misspelling, one name said two ways (Francina / Francine).
- The text has no punctuation and sentences often start with a small letter.

## Waiting for
Jun checks `bench/results/C/samples_for_jun.md`, then sets `ok_C_samples: yes` in `notes/bench_control.md`. Stage D (Sonnet, `translate_eval.py`) can be written before that, but no judge result counts until the samples are checked.
