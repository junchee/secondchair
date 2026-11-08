# Free speech-recognition experiments and what goes into the build (2026-11-08)

Setup: whisperkit-cli, small model, English forced (`--language en`), 4 AMI pieces (2220 clean tokens), `bench/analysis_F_target.py`. Stages A-F in `bench/reports/`.

## Results
| experiment | Missing | Wrong | Key | verdict |
|---|---|---|---|---|
| small, default (reference) | 10.7% | 6.2% | 90% | |
| turbo | 14.1% | 5.4% | 85% | worse, more memory: do not switch |
| speech detection (VAD) on / off | 10.7 / 10.0% | 6.2 / 8.4% | 90 / 89% | no clear difference: leave |
| `--prompt` with AMI meeting terms | 16.9% | 5.2% | 88% | worse (Missing +6 points); inline labels 11 -> 3 |
| thresholds (no-speech 0.9, logprob -2.0) | not finished | | | interrupted; no result |
One run per setting, 4 pieces: differences of a few points are not firm.

## Into the build (v1_8NOV2026)
1. Sound labels inside a line (`[BLANK_AUDIO]`, `(laughs)`, `[MUSIC]`) are removed before translation: `textclean.py`, `remote.py` (11 labels reached the translator in 4 pieces).
2. Repeat guard: `transcribe_stream.drop_repeats` already removes 3+ repeated groups in the app; nothing to add.

## Not changed
- Turbo, VAD setting: no gain.
- Briefing terms already go to Whisper as `initial_prompt` in the Python path. The CLI test suggests this may lose words. Not confirmed: compare with and without on Jun's own briefing before changing.
- Translation is fine on clean text (T0 94-98% right); the loss is in recognition (T1 75% on non-overlapped sentences).

## Open (not measured)
- Language: the bench forced English, so nothing compares forced language with automatic detection. Test: same 4 pieces without `--language`.
- `small.en` (English-only model): a guess that it makes fewer wrong words; needs Jun's OK to download; breaks Korean on the same stream, so only as a per-meeting choice.
- Short isolated answers and numbers are heard as "okay" or lost; Anne's filters (language share under 50%, no-speech) may also drop short true answers. Measure at stage I.
- Threshold and temperature-fallback experiment: redo (use `--extra=--logprob-threshold=-2.0`; a negative value needs the `=` form).
- `bench/run_asr.py` has a new `--extra` option (one whisperkit-cli argument each).
