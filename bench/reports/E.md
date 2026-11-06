# Stage E report (2026-11-06)

Run by the main session, not a Haiku subagent: the commands were short and needed Jun's key and an Anne-free Mac. Scope as in the runbook: 4 development pieces, ASR model small, translator = the app's (DeepSeek v4.1 flash, prompt variant `app`).

## What ran
1. `python3 bench/run_asr.py --asr-model small --piece ...` (whisperkit-cli, file mode, small model from `~/AnneProto/model`): 4 pieces, 1242 s of audio in 97 s in total (0.06-0.09x real time; one 10 s check first). Words: 605, 761, 538, 484. Texts in `bench/results/asr/small/` (local).
2. `python3 bench/translate_eval.py --asr-model small --piece ... --run-name E_small`: 364 sentences, conditions T0 (reference English) and T1 (ASR text on the reference sentences). Estimate $4.86; spent $5.00; **the run stopped at the $5 budget before it was finished**. Output `bench/results/E_small/` (local; rows.jsonl, summary.txt).

## The run is incomplete
All 728 translations exist (reference Korean for all 364 sentences, candidate Korean for all rows). Judging is missing for: TS3003a.cut01 (T0: 45 of 82 missing; T1: all 82), TS3003a.cut04 (all 172). The summary table mixes pieces unevenly (T0 includes 37 judged TS3003a.cut01 sentences, T1 none), so use the figures below, which are from the two fully judged pieces only. Finishing needs about 300 judge calls, about $1.2 more (total about $6.2); not started, Jun decides.

## Numbers (ES2004a.cut02 + IS1009a.cut02, 194 sentences, judge = Sonnet v2)
| | T0 reference English | T1 ASR text (small) |
|---|---|---|
| Meaning right | 92.3% | 58.8% |
| right + partly | 95.4% | 66.5% |
| content sentences only: right | 88.5% | 52.3% |
| content only: right + partly | 93.1% | 63.8% |
| critical errors per 100 sentences | 3.1 | 35.1 |
(All 4 pieces, partial: T0 Meaning 94.7%, T_err minor 3.34 / major 0.30 / critical 0.36 per 100 words; T1 major 1.29, critical 4.45 per 100 words; major+critical in T1 by type: omission 2.84, wrong meaning 2.13, addition 0.52, name or number 0.26.)

## What the numbers say, and what they do not
- The translator itself is good on clean English (T0 about 92% right, 3 critical errors per 100 sentences). Nearly the whole loss happens before translation: with the ASR text the share of right sentences falls from 92% to 59%. This is the first number for the question "where is quality lost"; at stage F it still needs the cause.
- ASR-empty sentences: 95 of 364 in T1 (26%), 60 of them bare backchannels; in the two judged pieces 67 of 194. The 35 non-backchannel empty ones are real misses, or words that the alignment gave to a neighbour (a T1 limit noted at stage D: unmatched ASR words go to the previous sentence). Not separated yet which it is.
- Even sentences with ASR text are only 58% right (right + partly 70%): so errors in the recognised words matter as much as misses. MER, Missing, Invented and Key (`score_text.py`) were not computed on these 4 pieces yet; that is the next number to get, cheap and free.
- Offline file mode on 5-minute files is fast (0.08x). This is not the streaming speed of Anne (steps of 0.8 s on a window); that is measured at stage I. My earlier guess of 1-2 hours for ASR was wrong for this mode.
- One translator, one prompt variant, one ASR model: no comparison between models or prompts exists yet.

## Cost note
Planned about $4 for the 4 pieces, estimate $4.86, actual $5.00 and not finished (the estimate was low by about 20%). Reference translations (Opus) are cached and need no repeat.

## Next (Jun decides)
1. Finish the judging of the 2 remaining pieces (about $1.2) so that all 4 pieces count; or accept the 2 pieces as the first table.
2. Free: run `score_text.py` MER/Missing/Invented/Key on the ASR texts of the 4 pieces, and look at what the 35 non-backchannel empty sentences are (miss or alignment).
3. Stage F (Opus): read the table, say where quality is lost, pick the next changes. It waits for `ok_F_decision`.
