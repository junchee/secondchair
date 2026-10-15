# Meeting Copilot (Jun)

Mac app that listens to Zoom/Teams/Meet audio and shows, in two columns, a live transcript and context-aware suggestions (related prep material, what to say next). Prep material and meeting goals can be uploaded before the meeting.

## Decisions
- v1: Python backend + browser UI on localhost. Later port to a native Swift app (per-app audio capture via ScreenCaptureKit, overlay window hidden from screen share, menu bar).
- Audio: the user's audio settings stay their own. Only while secondchair runs, `native/route` (Swift) adds a temporary multi-output device (real output + BlackHole 2ch) as the default output and follows device changes; it restores and deletes it on exit. Mic captured separately. Target design (Core Audio process tap, no device changes at all): `docs/audio_routing.md`.
- STT: local Whisper (Apple M1).
- LLM: Qwen via OpenRouter, key in env var `OPENROUTER_API_KEY` (in `~/.zshrc`). Zero data retention is enforced per request (`provider: {zdr: true, data_collection: deny}`); Alibaba-hosted Qwen flash models are refused under it, open-weight Qwen on ZDR hosts works.
- Output: meetings mostly English. Bidirectional English <-> Korean translation per line is an option (`--translate`); it comes before "what to say next" suggestions.
- Participants will be told the meeting is being transcribed.

## Plan
1. Audio capture test (`audio_test.py`) — both system audio and mic must show signal
2. Whisper streaming transcription, speaker = system vs mic
3. Bidirectional EN <-> KO translation of each line (option), via OpenRouter/Qwen
4. Two-column browser UI
5. Suggestions (what to say next, related prep) from recent transcript + prep context
6. Prep upload (PDF/notes) and meeting goal
7. Polish: overlay, hotkeys, post-meeting summary, then Swift port

## Status
Step 1 passed: `audio_test.py` shows signal on both BlackHole 2ch (system) and mic. Python venv at `.venv/` (sounddevice, numpy, mlx-whisper).

Step 2 working: `transcribe_small.py` (whisper-small, about 1 s per Whisper call) and `transcribe_turbo.py` (large-v3-turbo, about 5 s per call), both via `transcribe_stream.py`. Audio is cut at pauses (0.5 s silence, max 10 s per line). Mic is picked by name (`MIC_NAME` in `audio_test.py`), never the macOS default input: that default once became BlackHole 2ch, so "MIC" silently duplicated the system audio. On speakers the mic is off (it would re-record the meeting).

Output routing (option B, 2026-10-15): `audio_output.Route` runs `native/route` (built with `swiftc` on first use). Tested: start/stop restores the output and leaves no device; kill -9 leaves the device (still audible) and the next start deletes it; parent death makes the helper restore within 1 s. Live test 2026-10-15: plugging headphones in while running moved the route to them and turned the mic on. Not yet tested: unplugging while running, AirPods. Hand-made "Multi-Output Device" and "Speakers + BlackHole" should be deleted in Audio MIDI Setup: macOS fell back to them after unplugging headphones (no sound). Known limit: volume keys do not work while the temporary device is the output.

Step 3 built, offline-tested: `--translate` detects en/ko per line (Whisper language probs, restricted to en and ko), transcribes in that language, and translates to the other with `translate.py` (`qwen/qwen3.5-9b`, cheapest that translated well, about 0.45-0.6 s, background thread). Tested with `say` voices (Samantha, Yuna): correct. Live test 2026-10-15 works (BBC news EN -> KO, Jun's Korean mic speech -> EN). Weak spot: lines cut mid-sentence are translated without context ("attack them." -> "공격해라"), and some English words are left untranslated.

## Working style
Guide step by step; Jun runs each step and reports results. Keep explanations short.
