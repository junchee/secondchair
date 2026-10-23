"""Streaming transcription with Whisper (MLX), speaker = system audio vs mic.

Shared code only. Run the browser app (python app.py) or a terminal version, with the venv active:
    python transcribe_small.py    (whisper-small, about 1 s per Whisper call on M1)
    python transcribe_turbo.py    (whisper-large-v3-turbo, about 5 s per call, more accurate)
Results are reported as events (see events.py).
While running, the system output plays on the user's real device and on BlackHole 2ch
(temporary device from native/route, removed on exit). The mic is off while on speakers.
Options: --no-mic (never use the mic), --no-switch (leave the output device alone),
--translate (detect English or Korean per line and translate to the other, via translate.py).

Audio is cut where the speaker pauses, not at fixed intervals, so each line is
roughly one sentence and words are not split between two Whisper calls.

The first run of each version downloads its model. Press Ctrl+C to stop.
"""

import argparse
import fcntl
import itertools
import queue
import re
import signal
import sys
import threading
import time

import mlx.core as mx
import mlx_whisper
import numpy as np
import sounddevice as sd
from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
from mlx_whisper.transcribe import ModelHolder

import audio_output
from audio_test import MIC_NAME, SYSTEM_NAME, find_input, find_mic
from events import Settings, fan_out, print_event
from bubbles import Grouper
import prep
from echo import EchoFilter
from translate import Translator
from voice_out import VoiceOut

WHISPER_RATE = 16000
POLL_SECONDS = 0.2  # how often the main loop collects new audio
# An empty outlined bubble at the bottom the moment speech starts. Off (Jun, 2026-10-22): with short pauses it
# came and went with every fragment and made the page jump; the next bubble appears with its first text.
SHOW_EMPTY_BUBBLE = False
# While a line is spoken, Whisper hears the audio so far again about this often (0 = never) and shows it as a draft.
DRAFT_SECONDS = 1.0
DRAFT_MIN_SECONDS = 0.8  # no draft for a shorter line
MAX_TOKENS = 160  # enough for the longest allowed line (20 s); caps the length of any loop
LANGUAGES = ("en", "ko")  # with --translate, each line is detected as one of these

# Segmenting. A frame counts as speech when it is clearly louder than the background
# noise, which is tracked per source (the mic has room noise, BlackHole has none).
# The pause that ends a line and the maximum line length are live settings (events.Settings).
FRAME_SECONDS = 0.03
PREROLL_SECONDS = 0.3  # audio kept before speech starts, so the first word is not clipped
MIN_SPEECH_SECONDS = 0.3  # shorter bursts (a click, a cough) are dropped
SPEECH_RATIO = 3.0  # speech = this many times louder than the noise floor
MIN_SPEECH_RMS = 0.003  # and never quieter than this


class Segmenter:
    """Collects 16 kHz audio and returns complete segments, cut at pauses.

    Each segment comes with its level: the RMS over its speech frames. A cough, a key click
    or a fan makes a segment too, but a quiet one: Whisper turns those into "Thank you."
    """

    def __init__(self, settings):
        self.settings = settings
        self.frame = int(WHISPER_RATE * FRAME_SECONDS)
        self.noise_floor = 0.01
        self.reset()

    def reset(self):
        self.frames = []
        self.leftover = np.zeros(0, dtype=np.float32)
        self.speech_seconds = 0.0
        self.silence_seconds = 0.0
        self.speech_energy = 0.0  # sum of squared RMS over the speech frames

    def current(self):
        """The audio collected so far for the line being spoken, or None when nobody is speaking."""
        return np.concatenate(self.frames) if self.speaking and self.frames else None

    @property
    def speaking(self):
        """True while a segment with real speech (as long as the shortest kept) is being collected."""
        return self.speech_seconds >= MIN_SPEECH_SECONDS

    def _is_speech(self, frame):
        rms = float(np.sqrt(np.mean(np.square(frame))))
        # Follow the floor down at once, up only slowly, so speech does not raise it.
        if rms < self.noise_floor:
            self.noise_floor = rms
        else:
            self.noise_floor = 0.999 * self.noise_floor + 0.001 * rms
        speech = rms > max(self.noise_floor * SPEECH_RATIO, MIN_SPEECH_RMS)
        if speech:
            self.speech_energy += rms * rms
        return speech

    def feed(self, audio):
        audio = np.concatenate([self.leftover, audio])
        n_full = len(audio) // self.frame * self.frame
        self.leftover = audio[n_full:]
        segments = []
        for start in range(0, n_full, self.frame):
            frame = audio[start : start + self.frame]
            self.frames.append(frame)
            if self._is_speech(frame):
                self.speech_seconds += FRAME_SECONDS
                self.silence_seconds = 0.0
            else:
                self.silence_seconds += FRAME_SECONDS

            if self.speech_seconds == 0:
                # Still waiting for speech: keep only the pre-roll.
                keep = int(PREROLL_SECONDS / FRAME_SECONDS)
                del self.frames[:-keep]
                continue

            length = len(self.frames) * FRAME_SECONDS
            pause, longest = self.settings.pause_seconds, self.settings.max_line_seconds
            if self.silence_seconds >= pause or length >= longest:
                if self.speech_seconds >= MIN_SPEECH_SECONDS:
                    frames_of_speech = self.speech_seconds / FRAME_SECONDS
                    level = float(np.sqrt(self.speech_energy / frames_of_speech))
                    segments.append((np.concatenate(self.frames), level))
                self.frames = []
                self.speech_seconds = 0.0
                self.silence_seconds = 0.0
                self.speech_energy = 0.0
        return segments


class Source:
    """One audio input, collected into a buffer that the main loop drains."""

    def __init__(self, label, device_index, settings):
        self.label = label
        info = sd.query_devices(device_index)
        self.rate = int(info["default_samplerate"])
        self.channels = min(info["max_input_channels"], 2)
        self.buffer = []
        self.lock = threading.Lock()
        self.segmenter = Segmenter(settings)
        self.stream = sd.InputStream(
            device=device_index,
            channels=self.channels,
            samplerate=self.rate,
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status):
        mono = indata.mean(axis=1).copy()
        with self.lock:
            self.buffer.append(mono)

    def take(self):
        with self.lock:
            if not self.buffer:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self.buffer)
            self.buffer = []
        return audio


def to_whisper_rate(audio, rate):
    if audio.size == 0 or rate == WHISPER_RATE:
        return audio.astype(np.float32)
    n_out = int(round(audio.size * WHISPER_RATE / rate))
    positions = np.linspace(0, audio.size - 1, n_out)
    return np.interp(positions, np.arange(audio.size), audio).astype(np.float32)


def drop_repeats(text):
    # Whisper sometimes loops on one phrase ("I have a look. I have a look. ..." or "f***ing f***ing ...").
    # A group of 1-12 words that comes 3 or more times in a row is kept once.
    words = text.split()
    key = [re.sub(r"\W", "", word).lower() or word for word in words]
    out, i = [], 0
    while i < len(words):
        for size in range(1, min(12, len(words) - i) + 1):
            group = key[i:i + size]
            repeats = 1
            while key[i + repeats * size:i + (repeats + 1) * size] == group:
                repeats += 1
            if repeats >= 3:
                out.extend(words[i:i + size])
                i += repeats * size
                break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def detect_language(audio, model):
    """English or Korean, whichever Whisper finds more likely. Other languages are ignored,
    so a short or unclear line cannot come out as, say, Japanese."""
    whisper = ModelHolder.get_model(model, mx.float16)
    mel = log_mel_spectrogram(audio, n_mels=whisper.dims.n_mels, padding=N_SAMPLES)
    _, probs = whisper.detect_language(pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16))
    return max(LANGUAGES, key=lambda code: probs.get(code, 0.0))


def transcribe(audio, model, language="en", prompt=None):
    """`prompt` (English only) starts Whisper's prompt: what the meeting is about and its names and terms."""
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=model,
        language=language,
        initial_prompt=prompt if language == "en" and prompt else None,
        condition_on_previous_text=False,
        temperature=0.0,  # no retries at higher temperatures, which made loops slow
        sample_len=min(MAX_TOKENS, 16 + int(12 * len(audio) / 16000)),  # a short line cannot hold a long loop
    )
    return drop_repeats(result["text"].strip())


LOCK_PATH = "/tmp/secondchair.lock"


def stop_on_sigterm(signum, frame):
    raise KeyboardInterrupt  # same clean shutdown as Ctrl+C


def claim_single_instance():
    """Exit if secondchair already runs: two route helpers would delete each other's device."""
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("secondchair is already running (app.py or transcribe_*.py). Stop it first.")
        sys.exit(1)
    return lock  # keep it open: the lock lasts until this process ends


class Hooks:
    """Where the host (app.py) joins the start and end of a meeting. The terminal versions use this."""

    def begin(self):
        """A new meeting starts: open its files, clear what the page shows."""

    def finish(self):
        """The meeting ended: make the final summary and save. Returns where it was saved, or None."""
        return None


class Engine:
    """One run of the program holds many meetings.

        idle --start--> running <--pause/resume--> paused --end--> ending --> idle

    A meeting owns the capture streams and the output route: End restores the sound output and
    lets go of them, Start makes them again. Pause keeps the output connected (so the sound does
    not drop and come back) and only stops listening: nothing is transcribed or recorded.
    What lives for the whole run: the model, the translator, and the virtual microphone
    (voice_out.py), which keeps passing Jun's real voice to Zoom while the program is open.
    """

    def __init__(self, model, use_mic=True, switch_output=True, settings=None, emit=print_event,
                 voice=False, controls=None, hooks=None):
        self.model = model
        self.use_mic = use_mic
        self.switch_output = switch_output
        self.settings = settings or Settings()
        self.hooks = hooks or Hooks()
        self.state = "idle"
        self.last_saved = None
        self.commands = queue.Queue()
        self.quit_requested = False
        self.route = None
        self.sources = []
        self.bubbles = {}  # source label -> True while the page shows an in-progress bubble for it
        self.drafts = {}  # source label -> {"at", "samples", "text", "cost"} of its latest draft
        self.draft_lang = {}  # source label -> language of its latest line (the draft uses it, no detection)
        self.mic = None
        self.line_ids = itertools.count(1)
        self.last_status = None

        self.system_index = find_input(SYSTEM_NAME)
        if self.system_index is None:
            print(f"Could not find an input named '{SYSTEM_NAME}'. Run audio_test.py first.")
            sys.exit(1)
        self.mic_index = find_mic()
        if self.mic_index is None:
            print(f"Could not find '{MIC_NAME}' or another non-BlackHole input. Run audio_test.py.")
            sys.exit(1)

        self.voice_out = VoiceOut(self.mic_index, emit) if voice else None
        if self.voice_out:
            emit = fan_out(emit, self.voice_out.observe)  # it collects Jun's translated Korean lines
            if controls is not None:
                controls["voice"] = self.voice_out
        self.emit = emit
        self.translator = Translator(emit, lambda: self.settings.translate_model) if self.settings.translate_available else None
        self.grouper = Grouper()
        self.echo = EchoFilter()
        self.system_speech_at = 0.0  # when the meeting last had speech (for the echo check on speakers)
        self.echo_drops = 0
        if controls is not None:
            controls["engine"] = self

        print(f"System audio: {sd.query_devices(self.system_index)['name']}")
        print(f"Microphone:   {sd.query_devices(self.mic_index)['name']}")
        print(f"Model: {model}")
        print("First run downloads the model, so the first line can take a while.")
        print("Ctrl+C to stop.\n")

    # ---- commands (from any thread; carried out by the loop in serve())

    def command(self, action):
        if action in ("start", "pause", "resume", "end"):
            self.commands.put(action)

    def request_quit(self):
        self.quit_requested = True

    def _handle_commands(self):
        while True:
            try:
                action = self.commands.get_nowait()
            except queue.Empty:
                return
            if action == "start" and self.state == "idle":
                self._start()
            elif action == "pause" and self.state == "running":
                self._pause()
            elif action == "resume" and self.state == "paused":
                self._resume()
            elif action == "end" and self.state in ("running", "paused"):
                self._end()

    # ---- the meeting's life

    def _set_state(self, state, **extra):
        self.state = state
        self.emit({"type": "session", "state": state, **extra})

    def _start(self):
        self.hooks.begin()
        self.line_ids = itertools.count(1)
        self.last_status = None
        self.bubbles = {}
        self.drafts = {}
        self.draft_lang = {}
        self.grouper.reset()
        self.echo.reset()
        self.echo_drops = 0
        if self.translator:
            self.translator.reset()
        try:
            self.route = audio_output.Route(self.emit) if self.switch_output else None
        except SystemExit as error:  # the sound helper did not start
            self.emit({"type": "info", "text": str(error)})
            self.hooks.finish()
            return
        self.mic = Source("MIC", self.mic_index, self.settings)
        self.sources = [Source("SYSTEM", self.system_index, self.settings), self.mic]
        for source in self.sources:
            source.stream.start()
        if self.voice_out:
            # The monitor plays on the real device; the default output also feeds BlackHole 2ch.
            route = self.route
            self.voice_out.real_output = (lambda: route.device) if route else (lambda: None)
        # The page was cleared by hooks.begin(): send it what it needs to draw itself again.
        self.emit(self.settings.as_event())
        if self.voice_out:
            self.emit(self.voice_out.as_event())
        self._set_state("running", new=True)

    def _drop_audio(self):
        for source in self.sources:
            source.take()
            source.segmenter.reset()
        self._clear_bubbles()

    def _show_bubble(self, source, force=False):
        if not SHOW_EMPTY_BUBBLE:
            return
        """Them only: an empty in-progress bubble as soon as speech has begun, so the page shows that
        someone is talking before the pause and Whisper have finished. The final line replaces it."""
        if source is self.mic or self.bubbles.get(source.label):
            return
        if force or source.segmenter.speaking:
            self.bubbles[source.label] = True
            self.emit({"type": "partial", "source": source.label, "text": "", "time": time.strftime("%H:%M:%S")})

    def _draft(self, source):
        """While a line is still being spoken, show what Whisper hears so far (grey, replaced by the final line).

        Every second or so the audio collected so far goes to Whisper again, so the English grows on the page
        before the pause that ends the line. Never for the mic, and never more often than Whisper can keep up with.
        """
        if source is self.mic or not DRAFT_SECONDS:
            return
        audio = source.segmenter.current()
        state = self.drafts.get(source.label)
        if audio is None or len(audio) < DRAFT_MIN_SECONDS * WHISPER_RATE:
            self.drafts.pop(source.label, None)
            return
        if state and (time.time() - state["at"] < max(DRAFT_SECONDS, state["cost"])
                      or len(audio) - state["samples"] < 0.4 * WHISPER_RATE):
            return
        started = time.time()
        language = self.draft_lang.get(source.label, "en")
        text = transcribe(audio, self.model, language, self._prompt())
        cost = time.time() - started
        print(f"[timing] draft {cost:.1f}s for {len(audio) / WHISPER_RATE:.1f}s of speech", file=sys.stderr, flush=True)
        self.drafts[source.label] = {"at": time.time(), "samples": len(audio), "text": text, "cost": cost}
        if self.state != "running" or not text or (state and state["text"] == text):
            return
        self.bubbles[source.label] = True
        self.emit({
            "type": "partial",
            "source": source.label,
            "text": text,
            "time": time.strftime("%H:%M:%S"),
            "bubble": self.grouper.peek(source.label, text, language),
        })

    def _prompt(self):
        return prep.whisper_prompt(self.settings.meeting_context, self.settings.terms)

    def _note_echo(self, text):
        self.echo_drops += 1
        print(f"[timing] mic line dropped as echo of the meeting: {text[:60]}", file=sys.stderr, flush=True)
        if self.echo_drops == 3:
            self.emit({"type": "info", "text": "The microphone is picking up the meeting from the speakers. Earphones give a cleaner transcript."})

    def _hide_bubble(self, source):
        if self.bubbles.pop(source.label, False):
            self.emit({"type": "partial", "source": source.label, "clear": True})

    def _clear_bubbles(self):
        for label in [label for label, shown in self.bubbles.items() if shown]:
            self.emit({"type": "partial", "source": label, "clear": True})
        self.bubbles = {}
        self.drafts = {}

    def _pause(self):
        self._drop_audio()
        self._set_state("paused")

    def _resume(self):
        self._drop_audio()  # what was heard while paused is not transcribed
        self._set_state("running")

    def _end(self):
        self._set_state("ending")
        self._clear_bubbles()
        for source in self.sources:
            source.stream.stop()
            source.stream.close()
        self.sources, self.mic = [], None
        if self.voice_out:
            self.voice_out.discard()
            self.voice_out.real_output = lambda: None
        if self.route:
            self.route.stop()
            time.sleep(0.1)  # let the reader thread report the "restored" line
            self.route = None
        saved = self.hooks.finish()  # the summary can take a few seconds; the sound is already back
        self.last_saved = saved or self.last_saved
        self._set_state("idle", saved=saved)

    # ---- listening

    def _listen(self):
        """One tick of a running meeting: report the status, then transcribe what was said."""
        route, mic, settings = self.route, self.mic, self.settings
        # On speakers the mic also records the meeting: echo lines are dropped below (see echo.py).
        on_speakers = bool(route and route.on_speakers())
        mic_on = self.use_mic
        status = {
            "type": "status",
            "output": route.device if route else None,
            "kind": route.kind if route else None,
            "mic": mic_on,
        }
        if status != self.last_status:
            if not self.last_status or mic_on != self.last_status["mic"]:
                mic.segmenter.reset()
            self.emit(status)
            self.last_status = status
        time.sleep(POLL_SECONDS)
        for source in self.sources:
            audio = to_whisper_rate(source.take(), source.rate)
            if source is mic and not mic_on:
                continue
            segments = source.segmenter.feed(audio)
            if source is not mic and (segments or source.segmenter.speaking):
                self.system_speech_at = time.time()
            self._show_bubble(source, force=bool(segments))  # also while Whisper works on a short line
            if not segments:
                self._draft(source)
            for segment, level in segments:
                if self.state != "running":
                    return  # paused or ended while we were busy: do not transcribe the rest
                if source is mic and level < settings.mic_min_level():
                    continue  # a click or room noise, not Jun: skip it before Whisper
                translating = self.translator is not None and settings.translate
                started = time.time()
                language = detect_language(segment, self.model) if translating else "en"
                text = transcribe(segment, self.model, language, self._prompt())
                print(f"[timing] {source.label} speech {len(segment) / 16000:.1f}s, whisper {time.time() - started:.1f}s", file=sys.stderr, flush=True)
                if not text:
                    self._hide_bubble(source)  # nothing was said after all
                    continue
                if source is mic and on_speakers and self.system_speech_at >= time.time() - len(segment) / 16000 - 0.5 \
                        and self.echo.is_echo(text):
                    self._note_echo(text)
                    continue  # the meeting heard through the speakers, not Jun
                line = {
                    "type": "line",
                    "id": next(self.line_ids),
                    "source": source.label,
                    "lang": language,
                    "text": text,
                    "time": time.strftime("%H:%M:%S"),
                }
                if source is mic:
                    line["level"] = round(level, 4)  # saved with the line, to tune mic_filter
                line["bubble"] = self.grouper.assign(line)  # lines cut mid-sentence share one bubble
                self.emit(line)
                if source is not mic:
                    self.echo.note_system(text)
                self.bubbles.pop(source.label, None)  # the page replaced the bubble with this line
                self.drafts.pop(source.label, None)
                self.draft_lang[source.label] = language
                if translating:
                    self.translator.submit(line)

    def serve(self, autostart=True):
        """Run until Ctrl+C, SIGTERM or request_quit(). A meeting running at the end is ended
        properly (summary and save). Returns where the last meeting was saved."""
        if self.voice_out:
            self.voice_out.start()
        try:
            if autostart:
                self._start()
            while not self.quit_requested:
                self._handle_commands()
                if self.state == "running":
                    self._listen()
                else:
                    if self.state == "paused":
                        self._drop_audio()  # nothing is kept while paused
                    time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            if self.state in ("running", "paused"):
                self._end()
            if self.voice_out:
                self.voice_out.stop()
        return self.last_saved


def run(model, use_mic=True, switch_output=True, settings=None, emit=print_event, voice=False,
        controls=None, hooks=None):
    """Run one program: meetings start and end inside it. See Engine."""
    lock = claim_single_instance()  # noqa: F841 (held for the life of the process)
    signal.signal(signal.SIGTERM, stop_on_sigterm)
    signal.signal(signal.SIGHUP, stop_on_sigterm)  # closing the Terminal window: stop cleanly too
    engine = Engine(model, use_mic, switch_output, settings, emit, voice, controls, hooks)
    return engine.serve()


def main(model):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-mic",
        action="store_true",
        help="never transcribe the mic",
    )
    parser.add_argument(
        "--no-switch",
        action="store_true",
        help="leave the output device alone (switch it yourself)",
    )
    parser.add_argument(
        "--translate",
        action="store_true",
        help="translate each line English <-> Korean (sends the text to OpenRouter)",
    )
    args = parser.parse_args()
    settings = Settings(translate=args.translate)
    if args.translate and not settings.translate_available:
        print("OPENROUTER_API_KEY is not set, so translation is off. Run: source ~/.zshrc")
    run(model, use_mic=not args.no_mic, switch_output=not args.no_switch, settings=settings)
