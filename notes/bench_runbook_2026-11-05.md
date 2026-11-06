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
A: DONE 2026-11-05 (Sonnet 5.5, nothing committed). `bench/score_text.py` (tokens, `align`, `score`: MER, Missing, Invented, Wrong, Key, SentF1; Korean by character, English by word), `bench/prepare_ami.py` (words XML -> `prepared/*.ref.json`, `cutNN.json/.txt`, manifest; fillers and truncated words dropped; key items are a heuristic: digits, mid-sentence capitals, words of 10+ letters), tests `bench/test_score_text.py` and `bench/test_prepare_ami.py` (27 pass: `cd bench && python3 -m unittest test_score_text test_prepare_ami`). The AMI XML layout is from memory, never run on a real file: stage B must check it (if `prepare_ami.py` fails or a piece looks wrong, stage A is redone, not patched by Haiku). Alignment is a full table: use pieces of a few minutes. B: DONE 2026-11-05 (Haiku subagent; Jun's OK for the download given in chat). 4 files, 131 MB, in `bench/audio/ami/`; XML layout as assumed, no code change; 12 pieces; 27 tests pass; licence CC BY 4.0. Report: `bench/reports/B.md`. C: DONE 2026-11-05 (Opus subagent, Jun said go in chat). `bench/prompts/` (reference translation, judge, README); 20 samples for Jun in `bench/results/C/samples_for_jun.md` (local only); prompts not run yet; Jun checked the 20 samples in chat (all 20 references fine, 16 of 20 verdicts agreed; judge severity needs one revision); waiting for `ok_C_samples` and `go_until D`. Report: `bench/reports/C.md`. D: DONE 2026-11-06 (Sonnet subagent; fake client only, 60 tests OK, dry run passes; report `bench/reports/D.md`; judge prompt v2 by Opus first). E-M: not started.

## Automatic run (decided with Jun 2026-11-05)
Jun may control it from the phone. Claude (the main session on Jun's Mac, awake and plugged in) runs the stages in order.
- **Who does a stage:** the main session starts it as a subagent with the model of the table (`Agent` with `model`: sonnet, haiku, opus), giving it the stage text of this file. Claude Haiku stages only run what exists (rule above).
- **Control:** `notes/bench_control.md`, edited by Jun in the GitHub phone app on branch `bench-auto`. Before every stage and at least every 20-30 minutes while waiting, `git pull --rebase origin bench-auto` and read it: `stop`, `go_until`, the `ok_` switches, `budget_usd_per_batch`, `note`. A switch is never set by Claude.
- **Reports:** after each stage Claude writes `bench/reports/STAGE.md` (at most 60 lines: what ran, the numbers, what is next), updates the Status line and the `status_` lines of the control file, and runs `bash bench/auto_commit.sh "message"`. That script stages only the allowed paths, refuses on anything that looks like a key, and pushes only `bench-auto`.
- **Stops (ask Jun, send a phone notification, wait for the switch):** B download (`ok_B_download`), C 20 samples (`ok_C_samples`), F and L decisions, the capture check of H (it plays sound: `ok_capture_check`), M (`ok_M_apply`), any failure of a Haiku stage, any paid batch whose estimate is over `budget_usd_per_batch`.
- **Never:** push `main`; `git add -A`; commit audio, `bench/results/`, `private/`, keys, transcripts or copyrighted clip texts; touch `user_settings.json` or start Anne; run two writers on the same files. Jun merges `bench-auto` into `main`.
- **Mac:** `request_keep_awake` at the start; if the Mac was asleep or offline, check `git status` and the last cache before continuing.
