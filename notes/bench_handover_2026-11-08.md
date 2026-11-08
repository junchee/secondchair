# Handover: the automatic speech and translation test (2026-11-08)

Everything below is on the branch `bench-auto` (pushed). Start any new session (laptop, desktop app or terminal) with:

> Read notes/bench_handover_2026-11-08.md, notes/bench_control.md and bench/reports/F.md. Continue from "Next".

## State
- Stages A-F are done (reports `bench/reports/A..F`; status lines in `notes/bench_runbook_2026-11-05.md` and `notes/bench_control.md`). Stage G (design of `SentenceEngine`) is not started. The switches in the control file are Jun's; Jun has approved each stage in chat so far (B, C, D, E scope, F).
- Result of F in one paragraph: on one-speaker (non-overlapped) AMI sentences the translator is fine (T0 98% right) and the recogniser loses most (T1 75% right). Part of the T1 loss is a bench error (recognised words handed to the wrong sentence). Turbo and the CLI speech detection do not help. Jun's target is one main speaker (lectures, talks, Q&A), not fast discussion.
- Judge: `bench/prompts/translation_judge.md` (v2); real Sonnet agreed with Jun on 26 of 28 cases. Jun prefers that reference translations and judging run in subagents inside the subscription, not through the paid OpenRouter API (spent so far about $5.16; the translator under test, DeepSeek, costs cents).

## Next (in order; details and commands in `bench/reports/F.md`)
1. Bench fix: T1 assignment in time order and digits normalised (`translate_eval.assign_asr`); add a test; rerun T1 translation (about $0.03).
2. Judge TS3003a.cut01 and cut04 (T1, and the T0 gaps) by a subagent. Needs a small export/import script for the judge prompt (not written).
3. Strip sound labels inside a line and add a loop guard before translation (`remote.py`).
4. Free ASR experiments: meeting-term prompt, thresholds, small.en (download needs Jun's OK).
5. Translation prompt variants `speech`, `context4`.
6. A lecture + Q&A test set: Jun has no recordings; public candidates are in F.md (licences to check, download only with Jun's OK).
7. Then stage G (Opus design), H (build `SentenceEngine`, `anne-bench`), I (baseline of the live streaming way), J-K (sweeps), L-M.

## What is NOT in git (this Mac only; the project folder is in iCloud Documents, so another Mac with the same iCloud account may have it, but check that the files are really downloaded)
| path | what | how to recreate |
|---|---|---|
| `bench/audio/ami/` (332 MB) | 3 AMI meetings (CC BY 4.0), annotations, `prepared/` | stage B commands in `bench/reports/B.md`; `python3 bench/prepare_ami.py --ami-dir bench/audio/ami` |
| `bench/results/cache/` (6 MB) | Opus reference Korean for 364 sentences (cost $2.78), candidate translations, judge answers | rerun `translate_eval.py` (pays again) or copy the folder; keys are hashes of model, prompt and input, so a copy works on any Mac |
| `bench/results/E_small/`, `asr/`, `F/`, `C/` | rows, ASR texts for small/turbo with and without detection, analysis, Jun's 20 sample answers | rerun `run_asr.py`, `translate_eval.py`; `C/jun_answers.md` is Jun's own check and cannot be recreated |
| `~/AnneProto/model` (small, 464 MB), `~/AnneProto/tokenizer`, `~/AnneProto/turbo` (619 MB) | WhisperKit models used by `run_asr.py` | download with `whisperkit-cli`; first start compiles for the Neural Engine (small about 3 min, turbo longer on 8 GB) |
| `OPENROUTER_API_KEY` | in `~/.zshrc` of this Mac | Jun gives a key; never in the repo; run paid commands as `zsh -ic '...'` so the key is read |

## Pitfalls met
- Anne must be closed while `whisperkit-cli` runs (8 GB Mac); closing it is Jun's action.
- In zsh a variable holding several arguments is not split: use an array (`P=(--piece a --piece b)` and `"${P[@]}"`).
- The turbo model sits in a nested folder: pass `--model-path ~/AnneProto/turbo/models/argmaxinc/whisperkit-coreml/openai_whisper-large-v3-v20240930_turbo_632MB` to `run_asr.py`.
- A cost estimate of `translate_eval.py` was about 20% low; the tool stops at the budget (`--budget-usd`, default from the control file) and resumes from the cache.
- Commit only through `bash bench/auto_commit.sh "message"` (allowed paths, key check, pushes only `bench-auto`); never `git add -A`; never commit audio, `bench/results/`, `private/`, keys or long AMI quotes. Jun merges `bench-auto` into `main`.
- Do not start Anne, play sound or press Quit while Jun may use the Mac without asking. Test with fake audio and port 8799.

## The app
`bash app/build.sh` builds `~/AnneApp/build/Anne.app` (11 s; ad-hoc signed; rebuilt on 2026-11-08, not started; the Swift code is unchanged since commit e5904e0). A real test of the build (Start, speech, End) has not been done since then; Jun will run it himself or ask for a fake-audio test.
