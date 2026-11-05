# Test runbook: stages and which Claude Code model does each (2026-11-05)

Design: `notes/speech_test_design_2026-11-05.md`. Direction: English -> Korean first. Sample: AMI (CC BY 4.0; ES2004a, IS1009a, TS3003a + manual annotations 1.6.2; 125 MB; Jun's OK needed before the download).

Jun switches the model in the app before each stage. Start each stage in a **new session** with:

> Read notes/bench_runbook_2026-11-05.md and do stage X only. Update its Status line and stop.

## Rules for every stage
- Do only the stage named. Record the outcome in the Status line here; results go to `bench/results/` (git ignores it).
- Never start Anne, play sound or touch `user_settings.json` and `transcripts/`. Do not commit; Jun decides. Audio stays in `bench/audio/`.
- Long runs go in the background and write `summary.txt`. Read the summary, not the raw logs.
- Every paid batch has a budget limit and a printed estimate first; it resumes from a cache and never repeats a finished call.

**Haiku stages only run what exists.** If a command fails or a number looks wrong: stop and report the command and the last 20 lines. Do not edit code or explain causes.

## Stages

| Stage | Model | Work | Done when |
|---|---|---|---|
| A | Sonnet | `bench/prepare_ami.py`: words XML -> reference text, word times, sentence ends, key items, 5-minute cuts. `bench/score_text.py`: `MER`, `Missing`, `Invented`, `Wrong`, `Key`, `SentF1`, with unit tests on made-up text | Tests pass |
| B | Haiku | Download the 4 files (after Jun's OK), run prepare and the tests | Manifest written, sizes checked |
| C | Opus | Write the prompts: reference translation, translation judge (`Meaning`: right / partly / wrong; `Critical`; `T_err` by type) | Prompts fixed; 20 samples for Jun to check are ready |
| D | Sonnet | `bench/translate_eval.py`: runs T0 and T1 for a list of models and prompts; cache, budget limit, resume. ASR text from `whisperkit-cli` | Dry run on 1 minute passes |
| E | Haiku | Run ASR (turbo, small) and the T0 and T1 batches; write the table | `summary.txt` written |
| F | Opus | Read the table; say where quality is lost; update the goals and pick the next changes | Decision written here |
| G | Opus | Design `SentenceEngine` (decisions out of `Speech.swift`, a clock, all values as parameters) | Design written, Jun OK |
| H | Sonnet | Build `SentenceEngine` and `anne-bench`; extend `bench/score.py`: delays, `NE`, `Burst`, `Noise`, `Loops` | File and real capture give the same result once |
| I | Haiku | Baseline run: current settings, all samples. T2 and T3 become possible here | `summary.txt` written |
| J | Sonnet | Write the sweep and search scripts (one value at a time, then Optuna) | Dry run passes |
| K | Haiku | Overnight sweep | `summary.txt` written |
| L | Opus | Choose settings and rule; check on held-out samples; say what to build | Decision written here |
| M | Sonnet | Apply the chosen settings to Anne | Regression set passes |

T2 (our cuts) needs `anne-bench`, so it comes at stage I, not with T0 and T1.

Models used inside the tests are separate from the Claude Code model: reference translation Opus, repeated judging Sonnet (Haiku only if it agrees with Sonnet on a sample), translators under test as listed.

## Status
A: not started. B: not started (waiting for Jun's OK). C-M: not started.
