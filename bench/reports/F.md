# Stage F report (2026-11-06, Opus)

## Decision
- Jun's target is one main speaker (lectures, talks, Q&A). For that target the main numbers are the ones on words and sentences without overlap, not the AMI totals.
- On clean sentences the translator loses little (T0 98% right); the recogniser loses most (T1 75% right, 88% right or partly). On clean words small misses 10.7%, of which about 3 points are repeats and fillers that the AMI reference keeps.
- Part of the measured loss is the bench itself: the T1 step gives recognised words to the wrong reference sentence when parts are out of time order or numbers are written as digits. The "lost" 41-word sentence and most "lost" numbers were heard. Fix the bench before any tuning.
- Turbo and the CLI speech detection are not better on clean words. Do not switch the engine.
- Next, in order: fix the T1 assignment and scoring; judge the TS3003a pieces (the best one-speaker proxy) by a subagent; then free ASR tests (meeting-term prompt, thresholds, small.en) and the cheap translation-side guards (sound labels, loops, `speech` prompt).
- Before tuning for the target, build a small lecture + Q&A set. AMI stays the hard case for overlap.
- These are AMI numbers in offline file mode with the small model. They are not Anne's live streaming numbers (stage I).

## Numbers (recomputed from `bench/results/E_small/rows.jsonl` and the ASR texts; scripts `bench/analysis_F_*.py`)
Judged in both T0 and T1: 191 sentences of ES2004a.cut02 and IS1009a.cut02 (E.md used 194; same result within 0.5 points).

| set | sentences | T0 right | T1 right | T1 right+partly | critical / 100 sentences T1 |
|---|---|---|---|---|---|
| all | 191 | 93.7% | 59.2% | 67.0% | 34.6 |
| **no overlapped word (target proxy)** | 48 | 97.9% | 75.0% | 87.5% | 12.5 |
| same, content only | 38 | 97.4% | 68.4% | 84.2% | 15.8 |
| under 25% overlapped words | 79 | 92.4% | 74.7% | 84.8% | 16.5 |
| mostly overlapped (half or more) | 95 | 94.7% | 49.5% | 53.7% | 46.3 |
Overlap = another speaker's word overlaps by more than 0.1 s. 48 sentences give a range of about +-12 points.

Why T1 is not right (78 sentences): T0 already not right 10; ASR text empty and not heard 17; words heard at that time but given to another sentence 19 (bench assignment or two speakers merged); many ASR errors 28; few or none 4. So the translator's own loss on correct input is about 3 of 35 exact sentences, plus the 10 that fail at T0.

ASR on clean words, all 4 pieces (2220 tokens; digits normalised to words):
| ASR | Missing | Wrong | Key (96 items) | Missing on overlapped words |
|---|---|---|---|---|
| small, CLI detection on | 10.7% | 6.2% | 90% | 50.3% |
| small, detection off | 10.0% | 8.4% | 89% | 46.2% |
| turbo, detection on | 14.1% | 5.4% | 85% | 52.7% |
TS3003a.cut01 (one speaker holds 538 of 570 words), small: MER 17.2%, clean Missing 5.6%, Wrong 5.6%, Key 89% (44 items). Its T1 translation is not judged yet: there is no translation number for the best proxy.

What the errors are (details and examples in `bench/results/F/*.txt`, local):
- Numbers: heard in most cases, but put in a neighbour sentence by the bench; one contradiction from overlap; "twelve fifty" read as 1,250 even by T0.
- Short isolated content words (one or two words) heard as a backchannel such as "okay". Seen on clean speech; an ASR problem.
- Wrong words that flip the sense (a currency heard as "bond", a job title as "sign").
- One loop: one word repeated 10 times (reference: once), translated as an addition. The CLI's default thresholds did not catch it.
- Sound labels inside a line (11 in the small texts) reach the translator and come out as Korean labels. Anne drops only lines that are only a label.
- A question mark added by the ASR turned an apology into "pardon?" (one case).
- Translator word sense on nearly exact text (physical vs abstract senses): 4 clean cases.

The judge: no sign of bias against T1 beyond the test material. It accepts an empty backchannel (36 of 43). It does penalise omitted overlapped speech that nobody could follow in one stream, and a misassigned sentence is counted twice (omission here, addition there). T1 additions judged major or critical: 8.

## Goals, revised for one main speaker (lecture, talk, Q&A)
| goal | value | status |
|---|---|---|
| `Meaning` main speaker | 90% right, 95% right+partly | keep; now 75% / 88% on 48 clean AMI sentences |
| `Meaning` audience questions | 80% right | new; needs the new set |
| `Critical` main speaker | 3 per 100 sentences or less | keep; now 12.5 |
| `Missing` content words | 3% or less | was 2% on all words; measure without repeats and fillers, which the reference keeps |
| `MER` main speaker | 8% or less | keep; now about 14% on clean words of TS3003a.cut01 |
| `Key` (terms, names, numbers) | 95% | raised from 90% (now 89-90%); terms matter more in lectures |
| `D_show` p50 / p90 | 2 / 3 s | relaxed from 1 / 2 s |
| `D_final` p50 / p90 | 4 / 6 s | relaxed from 3 / 6 s |
| `D_trans` first p50 / p90 | 3 / 5 s | relaxed from 2 / 4 s |
| `Loops`, `Noise`, `NE`, `Burst`, load | as before | unchanged |
Overlap goals: none. Report overlapped words separately and do not tune on them.

Needs a new set (lectures with Q&A): `Meaning` for audience questions, `Key` for specialist terms with a briefing, delays for long sentences, quiet far speech. Candidates (download only after Jun's OK; licences to check): Earnings-21/22 (calls: talk, then Q&A by phone; reported CC BY-SA 4.0), TED-LIUM 3 (talks; reported CC BY-NC-ND 3.0, so no shared derivatives), VoxPopuli English (parliament speeches; reported CC0), MIT OpenCourseWare lectures with transcripts (reported CC BY-NC-SA; some have Q&A), FLEURS (read sentences with English and Korean versions; reported CC BY 4.0; a check of the translator, not of speech). To ask Jun: one or two recordings of real lectures or seminars he attends, with permission, 10-20 minutes each with at least two audience questions; the briefing he would write for them; whether Korean speech from the mic must be counted in the target.

## Ranked changes
1. **Bench fix: T1 assignment in time order, digits normalised, content-word Missing.** Evidence: 19 of 78 T1 failures had their words heard at that time; the 41-word sentence goes from WER 1.00 to 0.07. Effect: the T1 number becomes honest (likely a few points higher; guess). Cost: about 1 h, Sonnet. Measure: rerun T1 translation (about $0.03) and judge the changed sentences. No Swift.
2. **Judge TS3003a.cut01 and cut04 T1 (and finish T0) by a subagent.** Evidence: these are the one-speaker proxy and have no T1 verdicts. Cost: about 250 judge calls inside Jun's subscription instead of about $1.2. No Swift.
3. **Strip sound labels inside a line and add a loop guard before translation.** Evidence: 11 labels and one 10x loop reached the translator. Effect: removes those additions; `Loops` = 0 on this data. Cost: tiny (Python, `remote.py`). Measure: label count, `Loops`, T1 additions. Testable now on the ASR texts.
4. **Briefing terms as a prompt to the recogniser.** Evidence: Key 89-90%, wrong terms and job titles. Effect: a guess; Whisper prompts can also add words. Cost: free test with whisperkit-cli if its version has a prompt option; in Anne a Swift change. Measure: Key, MER, Invented on clean words.
5. **Translation prompt `speech` and `context4`, and whole sentences only.** Evidence: 4 clean word-sense errors on near-exact text, 3 losses on exact text. Effect: a guess, maybe 2-5 sentences of 48. Cost: translations about $0.05, judge by a subagent. No Swift.
6. **small.en for English-only meetings.** Evidence: none yet; a guess that the English model has fewer wrong words. Cost: a model download (Jun's OK); breaks Korean speech on the same stream, so only as a per-meeting choice. Measure: clean Missing, Wrong, Key.
7. **Thresholds and temperature fallback.** Evidence: no segment crossed the default limits, including the loop window; fallback ran 4 times in one piece. Effect: likely small. Free test.
8. **Short answers and numbers.** Evidence: short clean content words heard as "okay"; Anne's filters (language share, no-speech) may also drop short true answers, which file mode does not show. Measure at stage I with Anne's filters on. A translation rule cannot recover them.
9. **Loudness normalisation for quiet audience questions.** No evidence in AMI (headset mix). A guess; test only on the new set.
10. **Display of uncertain words** (token log probability is in the reports). First a free check of whether low-probability tokens mark the wrong words.

## Experiments for the next step (a Sonnet agent can run these without judgement)
Free, no model call:
1. `python3 bench/analysis_F_loss.py && python3 bench/analysis_F_assign.py && python3 bench/analysis_F_target.py` (reproduces this report).
2. Bench fix (Sonnet edits `translate_eval.assign_asr`: sort sentences by start, normalise digits before alignment; add a test). Then `cd bench && python3 -m unittest discover`.
3. `whisperkit-cli transcribe --help` once; for each option that exists (prompt, no-speech, logprob and compression thresholds, temperature fallback), run small on the 4 wavs in `bench/results/asr/_wav/` into `bench/results/asr/small_<tag>/PIECE.txt` (same command as `bench/run_asr.py`, plus the option), then `python3 bench/analysis_F_target.py small small_<tag>`. Prompt text: the AMI meeting terms from the reference (remote control, LCD, buttons, Euro, Pound, designer). One option at a time.
4. Label and loop guard on the existing ASR texts: count labels and repeats before and after (`analysis_F_target.py` prints both).
5. Token log probability vs errors: read `PIECE.report/PIECE.json` `tokenLogProbs` and the alignment; report the share of wrong words among low-probability tokens.
Needs a judge (a subagent within Jun's subscription, not the paid API; it needs a small export/import script for the judge prompt):
6. Judge T1 of TS3003a.cut01 and cut04, and the T0 gaps.
7. After the bench fix: rerun T1 translation (DeepSeek, about $0.03, paid but tiny) and judge only the sentences whose text changed.
8. Variants `speech` and `context4` on T1 (about $0.05 of translation) and judge.
Needs Jun: the small.en download; any new data download; recordings for the lecture set.

## Not yet
- Turbo or a bigger engine: not better on clean words here (Missing 14.1% vs 10.7%) and costs memory on 8 GB.
- LLM correction of every sentence: the translator already does well on correct input, and the literature shows plain correction can raise WER.
- Tuning on overlapped speech, speaker separation or diarization: not the target.
- Optuna sweeps: wait for the bench fix, the one-speaker set and stage I.
- Finishing the paid judge batch: a subagent can do it.
- Stage G was not started.
