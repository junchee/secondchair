# Stage D report (2026-11-06)

Sonnet subagent built it; nothing paid was called. Before D, an Opus step revised the judge prompt (see below).

## Judge prompt v2 (Opus, before D)
- Rule: the judge first finds the speaker's main claim. A detail (one list item, a manner word, a hedge, an added explanation) is minor. A literal rendering that leaves the claim odd or empty is major. A word in the claim or stated reason replaced by another sense so the claim becomes a different plausible one is critical. Names, numbers, negation, who-did-what stay critical. An addition is major only if it adds a number, person, date, decision or commitment.
- Result by the Opus step's own judging: 20 of 20 samples match Jun (v1: 16 of 20); 8 new made-up cases all match. This has not been run with Sonnet yet: the first real step is `--judge-check` (about $0.1).
- Files: `bench/prompts/translation_judge.md` (v2), `translation_judge_v1.md` (copy), `judge_regression_cases.json` (8 made-up cases). Local: `bench/results/C/judge_v2_check.md`, `judge_regression_ami.json`.
- Unsure: C14 vs C15 differ only in where the changed verb sits (a list item vs the stated reason); Sonnet may not draw that line the same way. C12 may be read as critical. C06 depends on the reference for the currency.

## What was built (all in `bench/`)
`translate_eval.py` (steps: reference Korean by Opus, candidate Korean by the translator under test, judge by Sonnet; T0 = reference English, T1 = ASR text assigned to reference sentences; cache, budget, resume; `--dry-run`, `--fake`, `--judge-check`, `--piece`, `--max-seconds`), `llm.py` (client, cache, budget), `model_prices.json`, `test_translate_eval.py` (33 tests). `cd bench && python3 -m unittest discover`: 60 tests OK (27 old + 33 new).

## Dry run (fake client)
ES2004a.cut01, first 60 s, 13 sentences, 2 fake translators, 2 prompt variants, T0 and T1: plan 209 calls, estimate $0.49; run 1 made 127 calls and wrote 104 rows and a summary; run 2 made 0 calls (all cached). Summary numbers are from the fake judge and mean nothing.

## Defaults
- Reference Korean: `anthropic/claude-opus-5.5`; judge: `anthropic/claude-sonnet-5.5` (temperature 0). The repo never named Opus or Sonnet; these ids come from the pattern of `config/models.json` and exist in OpenRouter's public list. Change with `--reference-model`, `--judge-model`.
- Translator: `roles.translate[0]` of `config/models.json` (`deepseek/deepseek-v4.1-flash-1017`), prompt = the app's own `translate.build_request` (variant `app`). Other variants: `speech`, `context4`.
- Budget: `budget_usd_per_batch` of `notes/bench_control.md` (5).

## Cost of the full sample (all 12 pieces, 900 sentences, rough, +-30%)
| step | est. $ |
|---|---|
| Reference Korean (Opus), one-off | 4.78 |
| T0 translate + judge | 3.57 |
| T1 translate + judge | 3.57 |
| T0 + T1 total | about 11.9 |
One run is over the $5 budget, so the tool refuses. Run per meeting (`--piece ES2004a`, ...), about $4 each, or Jun raises the budget. Not built: OpenRouter `:batch` variants (half price), prompt caching.

## Limits
- The real client has never run (no key in the subagent): the first real call is its first test. Opus or Sonnet may ignore `temperature`.
- T1: an ASR word matching no reference word goes to the sentence before it. In T1 the translator's context is the ASR text; the judge and the reference prompt always see the reference English.
- The meeting description sent to Opus (AMI remote-control design team) is written from general knowledge; the term list is empty.
- Needs for T1: transcripts from stage E in `bench/results/asr/<model>/<piece>.txt`.

## Next
1. `python3 bench/translate_eval.py --judge-check` with the real key (about $0.1): checks Sonnet against Jun's 20 and the 8 new cases. Needs Jun's OK for a paid call.
2. Stage E (Haiku): ASR with whisperkit-cli (turbo, small) and the T0/T1 batches. Heavy on this 8 GB Mac; Jun's choice on how much to cut is open (fewer pieces, small only first).
