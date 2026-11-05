# Automatic speech and translation test: design (2026-11-05, waiting for Jun's OK)

Why: until now each change was judged by Jun listening to one news clip. Several things changed at once and some of my diagnoses were wrong. Goal: fixed samples, one command, numbers for every setting, no one listening.

## 1. What went wrong so far

| Problem seen | Cause found | Status |
|---|---|---|
| Words missing | Sound dropped while Whisper worked; crude line cutting | Fixed, not measured |
| Key words wrong ("파기환송") | Lines of 3-4 s give the model no context; 10-14 s pieces came out right on 2 samples | Sentence window built, not measured |
| Invented text ("오늘의 주식...", "MBC 뉴스 ...") | Short pieces with little speech; Whisper fills them with stock phrases | Not fixed |
| Same sentence 12 times | Model looped: 25 segments from 2.4 s of sound, all confirmed | Not fixed |
| Translation poor | Not measured. Suspects: wrong source text, fragments (the prompt tells the model to translate a fragment as a fragment), speed-first model | Unknown |
| Mistakes in my method | "Words cut" was my log cutting text at 60 characters; "turbo vs small" comparison was my own judgement with no reference; numbers taken under memory pressure; `bench/` from 2026-10-22 was not reused | Reason for this design |

Settings are also hard-coded in `Speech.swift` (0.8, 0.6, 1.2, 3.5, 20 s ...). They were chosen by hand.

## 2. The numbers (one report per run)

**Delay** (seconds after the word was spoken; p50 and p90)
- `D_show`: word first on screen
- `D_final`: word confirmed
- `D_trans`: translation first on screen, and final

**Accuracy / missing** (final text against the reference; Korean by character, English by word, as MER in the HiKE paper)
- `Missing`: deletions / reference length
- `Invented`: insertions / reference length
- `Wrong`: substitutions / reference length
- `MER` = the three together
- `Key`: share of marked key items heard right (names, numbers, terms such as 파기환송)
- `Noise`: invented words per minute on sound with no speech (music, silence, keys, coughs)
- `Loops`: repeated phrases per 10 minutes

**Stability and reading**
- `NE`: normalised erasure, text removed from the screen / final length, for source and translation (target from the literature: under 0.2)
- `Burst`: most lines confirmed within 1 s
- `SentF1`: sentence ends, against the reference

**Translation** (source: `T`)
- `T_err`: LLM judge errors per 100 words, by severity and type (omission, addition, wrong meaning, wrong name or number). Use it to rank systems; the literature shows it is weak at finding single error spans. A sample gets Jun's check to calibrate it.
- `T_loss`: how much is lost at each step (section 4)

**Cost**: Whisper seconds / audio seconds, peak memory, translation calls and $ per hour.

**Ranking**: first hard limits (load under 0.8, `D_final` p90, `Burst`, `Loops` = 0), then one score, for example `100 - (MER + 2*Missing + 2*Invented + 2*T_err ...)`. Limits and weights are for Jun to set; every number stays in the report. A Pareto table (quality vs delay) is shown as well, because the score hides the trade-off.

## 2a. Quality goal, in one line (proposal)

**Within 4 s of being said, 90% of sentences show a translation with the right meaning, and no wrong name, number or negation in the sentences that matter.**

- `Meaning`: share of sentences whose translation means the same as the reference, judged right / partly / wrong (LLM judge, a sample checked by Jun). Minimum 80%, goal 90%. Numbers are guesses until the baseline is measured.
- `Critical`: wrong names, numbers, negation, per 100 sentences.
- Every other number below explains why `Meaning` is high or low.

## 2b. Goals behind it (first proposal; guesses until the baseline is measured)

Measured on real meeting-like speech, with the default model of each Mac class.

| Number | Goal | Reason |
|---|---|---|
| `D_show` p50 / p90 | 1.0 / 2.0 s | WhisperKit paper: about 0.45 s on faster hardware |
| `D_final` p50 / p90 | 3 / 6 s | Paper: about 1.7 s per word; waiting for sentence ends costs more |
| `D_trans` first p50 / p90 | 2 / 4 s | Must stay readable while the meeting goes on |
| `MER` KO, EN | 8% or less | Clean-speech Whisper is 3-5% (HiKE paper); real speech is harder |
| `Missing` | 2% or less | Jun's main complaint |
| `Invented` | 1% or less | |
| `Key` | 90% or more | Names, numbers and terms carry the meaning |
| `Noise` | 0.5 words per minute or less | |
| `Loops` | 0 | Hard limit |
| `NE` source, translation | 0.2 or less | Re-translation paper |
| `Burst` | 2 lines per second or less | Jun: bubbles must not pour out |
| `T_err` major + critical | 1 per 100 words or less | Calibrate with Jun's check |
| Load | 0.7 or less | Must keep up on a busy Mac |
| Anne's memory | Measure first | Python and the Neural Engine share are not counted yet |

## 2c. What in the app can change

| Part | Now | Can be changed to | Moves |
|---|---|---|---|
| Sound | Tap, 48 to 16 kHz by averaging | Better resampler | `MER` |
| Speech detection | Energy, ratio 3.0, min 0.003, pre-roll 0.3 s | Silero VAD, other values | `Missing`, `Noise` |
| Engine | WhisperKit turbo 632 MB / small | Other sizes, Apple SpeechAnalyzer, a cloud service (changes the privacy promise) | `MER`, `Key`, load, delay |
| Decoding | Fallback 2, prefill off, timestamps on | Beam, thresholds, word times, language fixed per meeting | `MER`, `Loops`, load |
| Hints | Not passed to WhisperKit yet | Briefing terms as prompt tokens | `Key` |
| Confirm rule | Hand-made: step 0.8 s, pauses 0.6 and 1.2 s, stable 3.5 s, window 20 s | LocalAgreement, AlignAtt | `D_final`, `NE`, `Burst`, `Missing` |
| Filters | Thresholds, stock phrases, sound labels | Loop guard, minimum speech in a piece, compression ratio | `Invented`, `Noise`, `Loops` |
| Bubbles | One sentence each | One per speaker turn; turn cue "- " | `Burst`, readability |
| Translation input | Line + 2 lines of context, earlier translation | Whole sentences only, more context, correction of low-confidence words | `T_err` |
| Translation model | DeepSeek flash, reasoning off | Better model for the final pass, fast one for drafts | `T_err`, `D_trans`, cost |
| Translation prompt | Translate a fragment as a fragment | Tell it the text is from speech and may hold errors | `T_err` |
| Draft translation | None yet | Every N new words, at most every M seconds | `D_trans`, `NE`, cost |
| Context learned in the meeting (Jun's idea) | Only a Briefing made beforehand | Every few minutes an LLM reads the transcript and updates topic, names, terms; these go to the translation, the speech model's prompt, and optionally a correction of earlier bubbles. Risk: a wrong term spreads. Test: `Meaning` and `Key` with and without, per meeting minute | `Meaning`, `Key`, cost |
| Display | Grey draft, then final | Show translation only when stable | `NE`, `D_trans` |

## 3. Test bench

1. **Pull the decisions out of `Speech.swift`** into a `SentenceEngine` that takes sound blocks and a clock. Anne.app and the bench run the same code. All values become parameters.
2. **`anne-bench` (Swift command line):** reads a file and feeds it by a simulated clock. Whisper's measured time moves the clock, so delays stay realistic. No sound is played and no permission is needed, so it can run overnight while no one uses the Mac. Writes every event with times as JSONL.
3. **Check once** that a file through the bench gives the same result as the same sound through the real capture.
4. **Scoring in Python:** extend `bench/score.py`.
5. **Regression:** a 2-3 minute set runs before any change to speech or translation is shown to Jun.

## 4. Where translation quality is lost (do this first; no Swift needed)

Same sound, same translator, four inputs:

| Run | Input | Shows |
|---|---|---|
| T0 | Reference text, reference sentences | Best the translator can do |
| T1 | Final ASR text, reference sentences | Cost of ASR errors |
| T2 | Final ASR text, our cuts | Cost of bad cuts |
| T3 | The live stream with revisions | Cost of streaming |

Variants at T0-T2: translation model (fast vs better), prompt (fragment rule vs context), translating whole sentences only, and a correction step only for low-confidence words (plain LLM correction often raised WER in the literature; filtering by confidence is what worked).

## 5. Data

| Set | Language | Type | Licence to check |
|---|---|---|---|
| Zeroth-Korean | KO | Read speech | CC BY 4.0 |
| KsponSpeech (AI Hub) | KO | Spontaneous | Access and commercial terms unclear |
| HiKE | KO-EN mix | Code-switching, 2.2 h, labelled loanwords | Not stated in the paper |
| Common Voice | KO, EN | Mixed quality | Check |
| AMI | EN | Real meetings | Sources disagree; read the file in the download |
| Earnings22 | EN | Business calls, accents | Check |
| Own news clips | KO, EN | Fast real speech, closest to the failures | Copyrighted: local only, never in the repo |
| Jun's meetings | KO, EN | Real use | Only with consent of those present; local only |
| Noise set | none | Music, silence, keys, coughs | Check |

Audio stays in `bench/audio/` (git ignores it). Each sample has text, key items and sentence ends; reference translations are written by a strong model and a sample is checked by Jun. Variants: fast speech, low volume, noise, call codec, overlap.

Split: about 30 minutes each for tuning, and a held-out set (other speakers) touched only at the end, or the values will fit these clips only.

## 6. Search

What can vary: engine (WhisperKit small/turbo, other on-device engines), confirm rule (current hand-made rule, LocalAgreement, AlignAtt), speech detector (energy, Silero), step, pauses, stable time, window length, thresholds (no speech, log probability, compression), temperature retries, translation model, context lines, draft rules.

1. One value at a time, to see which ones matter.
2. Multi-objective search (Optuna) over the top 5, quality vs delay.
3. Best 3 on the held-out set; report with confidence ranges.
4. Same search on an 8 GB and a 16 GB+ Mac (or a rented one), since the best values depend on the machine.

Whisper results are cached by sound, model and options, so most runs do not repeat the slow step.

## 7. References

- Machacek, Dabre, Bojar 2023, Turning Whisper into Real-Time Transcription System (LocalAgreement): arXiv 2307.14743
- Machacek, Polak 2025, SimulStreaming / AlignAtt, IWSLT 2025: github.com/ufal/SimulStreaming
- Orhon et al. 2025, WhisperKit (hypothesis and confirmed text, latency definition): arXiv 2507.10860
- Arivazhagan et al. 2020, Re-translation versus Streaming: arXiv 2004.03643
- Google Research 2021, Stabilizing Live Speech Translation (erasure)
- Koenecke et al. 2024, Careless Whisper (hallucinations and non-vocal time): arXiv 2402.08021
- Paik et al. 2025, HiKE (Korean-English, MER, PIER): arXiv 2509.24613
- Kocmi, Federmann 2023, GEMBA-MQM (LLM translation judge): arXiv 2310.13988
- Naderi et al. 2024, LLM correction of ASR with confidence filtering, Interspeech
