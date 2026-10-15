# Meeting Copilot (Jun)

Mac app that listens to Zoom/Teams/Meet audio and shows, in two columns, a live transcript and context-aware suggestions (related prep material, what to say next). Prep material and meeting goals can be uploaded before the meeting.

## Decisions
- v1: Python backend + browser UI on localhost. Later port to a native Swift app (per-app audio capture via ScreenCaptureKit, overlay window hidden from screen share, menu bar).
- Audio: the user's audio settings stay their own. Only while secondchair runs, `native/route` (Swift) adds a temporary multi-output device (real output + BlackHole 2ch) as the default output and follows device changes; it restores and deletes it on exit. Mic captured separately. Target design (Core Audio process tap, no device changes at all): `docs/audio_routing.md`.
- STT: local Whisper (Apple M1).
- LLM: Qwen via OpenRouter, key in env var `OPENROUTER_API_KEY` (in `~/.zshrc`). Zero data retention is enforced per request (`provider: {zdr: true, data_collection: deny}`); Alibaba-hosted Qwen flash models are refused under it, open-weight Qwen on ZDR hosts works.
- Output: meetings mostly English. Bidirectional English <-> Korean translation per line is an option (on by default in `app.py`, `--translate` in the terminal versions); it comes before "what to say next" suggestions.
- Path to an app: (1) browser version, needs the venv and BlackHole; (2) Python bundled into a .app (no Python install, BlackHole still needed); (3) native Swift app with a process tap (no BlackHole).
- Participants will be told the meeting is being transcribed.

## Plan
1. Audio capture test (`audio_test.py`) — both system audio and mic must show signal
2. Whisper streaming transcription, speaker = system vs mic
3. Bidirectional EN <-> KO translation of each line (option), via OpenRouter/Qwen
4. Two-column browser UI
4b. Interpret: Jun's Korean -> English speech into the meeting (virtual mic); transcript saving; post-meeting summary
5. Suggestions (what to say next, related prep) from recent transcript + prep context
6. Prep upload (PDF/notes) and meeting goal
7. Polish: overlay, hotkeys, then Swift port

## Status
Step 1 passed: `audio_test.py` shows signal on both BlackHole 2ch (system) and mic. Python venv at `.venv/` (sounddevice, numpy, mlx-whisper).

Step 2 working: `transcribe_small.py` (whisper-small, about 1 s per Whisper call) and `transcribe_turbo.py` (large-v3-turbo, about 5 s per call), both via `transcribe_stream.py`. Audio is cut at pauses (0.5 s silence, max 10 s per line). Mic is picked by name (`MIC_NAME` in `audio_test.py`), never the macOS default input: that default once became BlackHole 2ch, so "MIC" silently duplicated the system audio. On speakers the mic is off (it would re-record the meeting).

Output routing (option B, 2026-10-15): `audio_output.Route` runs `native/route` (built with `swiftc` on first use). Tested: start/stop restores the output and leaves no device; kill -9 leaves the device (still audible) and the next start deletes it; parent death makes the helper restore within 1 s. Live test 2026-10-15: plugging headphones in while running moved the route to them and turned the mic on. Not yet tested: unplugging while running, AirPods. Hand-made "Multi-Output Device" and "Speakers + BlackHole" should be deleted in Audio MIDI Setup: macOS fell back to them after unplugging headphones (no sound). Known limit: volume keys do not work while the temporary device is the output.

Step 3 built, offline-tested: `--translate` detects en/ko per line (Whisper language probs, restricted to en and ko), transcribes in that language, and translates to the other with `translate.py` (`qwen/qwen3.5-9b`, cheapest that translated well, about 0.45-0.6 s, background thread). Tested with `say` voices (Samantha, Yuna): correct. Live test 2026-10-15 works (BBC news EN -> KO, Jun's Korean mic speech -> EN). Each line is sent with the two previous lines as context, over one kept-alive HTTPS connection. A line that ends mid-sentence is translated again when the same speaker's next line arrives (sent as a revised translation). Weak spot left: a fragment that starts mid-sentence ("attack them.") is still translated as if it were whole; transcription errors ("Gray painted" for "spray-painted") pass through.

Step 4 built and tested (2026-10-15): `python app.py [--model small|turbo]` serves `ui/index.html` on 127.0.0.1:8765 and opens it. Components report events (`events.py`); the terminal and the page get the same events (page via Server-Sent Events, full replay on reload). Page: Them/Me rows, original | translation columns, translation on/off (T), view Both/Original/Translation (V), text size, output and mic chips, "New lines" button when scrolled up, dark mode. Only one secondchair runs at a time (`/tmp/secondchair.lock`), since two route helpers would delete each other's device. Tested with `say` through the real route: lines, translations, revisions, toggle, reload.

Step 4b built (2026-10-15), Jun's request: the other side is only translated on the page; only Jun's speech is voiced.
- `voice_out.py`: a virtual mic ("BlackHole 16ch", override with `SECONDCHAIR_VOICE_DEVICE`) that Jun picks as the microphone in Zoom/Teams. "My voice" mode passes the real mic through; "Interpret" mode holds the mic back, collects translations of Jun's Korean MIC lines as an English draft, and speaks it with a macOS voice (`say`, best installed English voice) when Jun says "오케이" (or presses Enter, after editing if wanted). The monitor (on by default, 50%) plays the same speech in Jun's headphones via `monitor_play.py` on the real device, not the default output, which also feeds BlackHole 2ch. "다시" clears; a Korean line more than 3 s after the draft's last line replaces the draft (Jun said it again). Needs headphones (mic is off on speakers) and translation on.
- Page: My voice / Interpret (I), draft box (Enter speaks, Esc discards), Settings panel (longest line 4-20 s, pause 0.2-1.5 s, live), Stop button (same clean shutdown as Ctrl+C; closing the page does not stop secondchair).
- `record.py`: every session saved in `transcripts/` (gitignored): `.jsonl` as it happens, `.md` at stop with final translations. `summary.py`: at stop, Korean summary (핵심 요약, 결정 사항, 할 일, 열린 질문) with `qwen/qwen3.5-35b-a3b`, on top of the `.md` and shown on the page.
- Tested: voice path with BlackHole 2ch standing in (Whisper heard the spoken draft exactly); draft from Jun's real Korean mic line; Stop -> summary -> saved -> output restored. Not yet tested: BlackHole 16ch (Jun to install with `brew install --cask blackhole-16ch`) and a real Zoom/Teams call.

## Working style
Guide step by step; Jun runs each step and reports results. Keep explanations short.
