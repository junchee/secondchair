# Audio routing: target design

## Principles

1. Never change the user's audio settings (output device, input device, volume). Then there is nothing to restore, and a crash leaves no trace.
2. Capture what the meeting app plays, on whatever device it plays: built-in speakers, wired headphones, AirPods, USB headset, monitor.
3. Record the mic the user actually speaks into, and follow device changes while running.
4. Keep the user's speech when they use speakers. Remove the echo from the mic signal; do not mute the mic.
5. Plugging or unplugging any device needs no action from the user and no restart.
6. Show what is captured (app, mic name, live levels) and warn when a source stays silent while a meeting app is running.

## Current v1 (BlackHole + Multi-Output Device + SwitchAudioSource)

| Principle | Status | Problem |
|---|---|---|
| 1 | Fails | Switches the system output. Multi-Output Devices have no volume control, so the volume keys stop working while secondchair runs. If secondchair is killed, the output stays on a Multi-Output Device. |
| 2 | Fails | Works only for the two routes we built (wired jack, built-in speakers). With AirPods or a USB headset, sound goes to the built-in speakers instead. |
| 5 | Fails | After exit, unplugging headphones makes macOS fall back to "Multi-Output Device" (its headphones are gone): no sound. Observed 2026-10-15. |
| 3 | Partial | Mic is pinned to "MacBook Air Microphone". A user talking into AirPods or a USB mic is recorded through the laptop mic. |
| 4 | Fails | With speakers the mic is switched off, so the user's own speech is lost. |
| Setup | Heavy | BlackHole driver (admin), two Multi-Output Devices by hand, `switchaudio-osx`. Device names are hard-coded. |

The v1 design is a workaround that let us build transcription and translation. It cannot reach the principles above by adding rules.

## Target: Core Audio process tap

- `AudioHardwareCreateProcessTap` with a `CATapDescription` (macOS 14.2+; this Mac runs 26.5). The tap receives an app's audio before it reaches any output device, so the output device does not matter. Tap the meeting apps (zoom.us, Microsoft Teams), or all processes except secondchair.
- The tap is read through a private aggregate device that exists only inside our process. Other apps and macOS fallback never see it. It disappears when the process exits or crashes.
- Permission: one macOS prompt for system audio recording, plus the microphone prompt.
- Mic: the system default input, followed live with a property listener. Virtual devices (BlackHole and similar) are skipped. Manual override as a setting.
- Echo: echo cancellation on the mic with the tapped audio as the reference (Apple voice processing, or WebRTC AEC). With headphones it removes almost nothing; with speakers it keeps the user's speech.
- No BlackHole, no Multi-Output Devices, no `switchaudio-osx`, no device names in code.

### Implementation path

1. Spike: a small Swift command-line helper that taps all system audio and writes PCM to stdout. Python reads it in place of the BlackHole stream.
   Risk to settle first: whether a helper started from Terminal can get the system-audio permission, or whether it must be packaged as a minimal .app with a usage description.
2. Add the mic to the same helper (default input, live follow), so both streams share one clock.
3. Add echo cancellation.
4. Remove BlackHole, `audio_output.py` and the device-switching code. The helper's code moves into the Swift app later.

## Option B, in use now (2026-10-15): temporary Multi-Output Device

Jun chose this for now. `native/route.swift`, started by `audio_output.Route`:

- On start: takes the current default output (or, if that is virtual or an aggregate, built-in headphones, then built-in speakers), creates a public stacked aggregate "secondchair (<device>)" = that device (clock) + BlackHole 2ch (drift compensation), and makes it the default output. It must be public, or meeting apps could not play into it.
- While running: listens for device-list and default-output changes. If macOS or the user picks a real device (AirPods connect, menu bar choice), it rebuilds on that device. If its device disappears (headphones unplugged), it rebuilds on the fallback. If headphones appear while on speakers, it moves to them. Device kind comes from transport type and data source ('ispk' speakers, 'hdpn' jack; HDMI/DisplayPort count as speakers), not from names.
- On exit (SIGINT, SIGTERM, SIGHUP, or parent death): restores the real device and deletes the aggregate. A device left by kill -9 is deleted on the next start.

Compared with the principles: 1 still fails (it switches the output while running, and the volume keys do not work on an aggregate); 2 and 5 hold while running; 3 and 4 unchanged. The process tap remains the target.
