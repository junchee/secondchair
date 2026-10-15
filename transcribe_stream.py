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
from translate import Translator
from voice_out import VoiceOut

WHISPER_RATE = 16000
POLL_SECONDS = 0.2  # how often the main loop collects new audio
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
    """Collects 16 kHz audio and returns complete segments, cut at pauses."""

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

    def _is_speech(self, frame):
        rms = float(np.sqrt(np.mean(np.square(frame))))
        # Follow the floor down at once, up only slowly, so speech does not raise it.
        if rms < self.noise_floor:
            self.noise_floor = rms
        else:
            self.noise_floor = 0.999 * self.noise_floor + 0.001 * rms
        return rms > max(self.noise_floor * SPEECH_RATIO, MIN_SPEECH_RMS)

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
                    segments.append(np.concatenate(self.frames))
                self.frames = []
                self.speech_seconds = 0.0
                self.silence_seconds = 0.0
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
    # Whisper sometimes loops on one phrase ("I have a look. I have a look. ...").
    return re.sub(r"((?:\b\w+\b[ ,.?!]*){1,12}?)(?:\s*\1){2,}", r"\1", text).strip()


def detect_language(audio, model):
    """English or Korean, whichever Whisper finds more likely. Other languages are ignored,
    so a short or unclear line cannot come out as, say, Japanese."""
    whisper = ModelHolder.get_model(model, mx.float16)
    mel = log_mel_spectrogram(audio, n_mels=whisper.dims.n_mels, padding=N_SAMPLES)
    _, probs = whisper.detect_language(pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16))
    return max(LANGUAGES, key=lambda code: probs.get(code, 0.0))


def transcribe(audio, model, language="en"):
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=model,
        language=language,
        condition_on_previous_text=False,
        temperature=0.0,  # no retries at higher temperatures, which made loops slow
        sample_len=MAX_TOKENS,
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


def run(model, use_mic=True, switch_output=True, settings=None, emit=print_event, voice=False, controls=None):
    """Transcribe until Ctrl+C or SIGTERM. `settings` may be changed by another thread.

    With `voice`, Jun's speech can be sent into the meeting through the virtual mic
    (voice_out.py); the VoiceOut object is put in `controls["voice"]` for the page to drive.
    """
    lock = claim_single_instance()  # noqa: F841 (held for the life of the process)
    signal.signal(signal.SIGTERM, stop_on_sigterm)
    settings = settings or Settings()

    system_index = find_input(SYSTEM_NAME)
    if system_index is None:
        print(f"Could not find an input named '{SYSTEM_NAME}'. Run audio_test.py first.")
        sys.exit(1)
    mic_index = find_mic()
    if mic_index is None:
        print(f"Could not find '{MIC_NAME}' or another non-BlackHole input. Run audio_test.py.")
        sys.exit(1)

    voice_out = VoiceOut(mic_index, emit) if voice else None
    if voice_out:
        emit = fan_out(emit, voice_out.observe)  # it collects Jun's translated Korean lines
        if controls is not None:
            controls["voice"] = voice_out
    translator = Translator(emit) if settings.translate_available else None

    mic = Source("MIC", mic_index, settings)
    sources = [Source("SYSTEM", system_index, settings), mic]
    print(f"System audio: {sd.query_devices(system_index)['name']}")
    print(f"Microphone:   {sd.query_devices(mic_index)['name']}")
    print(f"Model: {model}")
    print("First run downloads the model, so the first line can take a while.")
    print("Ctrl+C to stop.\n")
    emit(settings.as_event())

    route = audio_output.Route(emit) if switch_output else None
    for source in sources:
        source.stream.start()
    if voice_out:
        voice_out.start()

    line_ids = itertools.count(1)
    last_status = None
    try:
        while True:
            # With speakers the mic re-records the system audio, so only listen with headphones.
            mic_on = use_mic and not (route and route.on_speakers())
            status = {
                "type": "status",
                "output": route.device if route else None,
                "kind": route.kind if route else None,
                "mic": mic_on,
            }
            if status != last_status:
                if not last_status or mic_on != last_status["mic"]:
                    mic.segmenter.reset()
                emit(status)
                last_status = status
            time.sleep(POLL_SECONDS)
            for source in sources:
                audio = to_whisper_rate(source.take(), source.rate)
                if source is mic and not mic_on:
                    continue
                for segment in source.segmenter.feed(audio):
                    translating = translator is not None and settings.translate
                    language = detect_language(segment, model) if translating else "en"
                    text = transcribe(segment, model, language)
                    if not text:
                        continue
                    line = {
                        "type": "line",
                        "id": next(line_ids),
                        "source": source.label,
                        "lang": language,
                        "text": text,
                        "time": time.strftime("%H:%M:%S"),
                    }
                    emit(line)
                    if translating:
                        translator.submit(line)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        for source in sources:
            source.stream.stop()
            source.stream.close()
        if voice_out:
            voice_out.stop()
        if route:
            route.stop()
            time.sleep(0.1)  # let the reader thread report the "restored" line


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
