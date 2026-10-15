"""Speak for Jun in the meeting through a virtual microphone.

In Zoom or Teams, choose VOICE_DEVICE ("BlackHole 16ch") as the microphone. secondchair sends:
    direct     Jun's real mic, unchanged: the others hear Jun's own voice
    interpret  the Avatar voice (beta): no live mic. What Jun confirms ("오케이" or Enter on the
               page) is spoken with a macOS voice. In every mode Jun's Korean is translated and
               collected as a draft shown on the page, for him to read out himself;
               "다시" clears it and saying the Korean again after a pause replaces it.
The other side's speech is never voiced; it is only translated on the page.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave

import numpy as np
import prefs
import sounddevice as sd

# Separate from BlackHole 2ch, which carries the meeting audio. Override with an env var to use
# another virtual device.
VOICE_DEVICE = os.environ.get("SECONDCHAIR_VOICE_DEVICE", "BlackHole 16ch")
RATE = 48000
MONITOR_PLAYER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_play.py")

# Spoken commands in interpret mode: a line made only of these words is a command, not speech.
SEND_WORDS = {"오케이", "okay", "ok", "보내", "보내줘", "전송"}
CLEAR_WORDS = {"다시", "취소", "cancel"}
# A Korean line this long after the draft's last line starts a new draft (Jun said it again);
# a quicker one continues the same statement.
NEW_DRAFT_AFTER_SECONDS = 3.0
WAIT_FOR_TRANSLATION_SECONDS = 3.0  # "오케이" right after speaking: let the last line translate


def command_of(text):
    """'send', 'clear' or None. Whisper may write "오케이." or "OK, OK." for the same word."""
    words = re.findall(r"[0-9a-z가-힣]+", text.lower())
    if words and all(word in SEND_WORDS for word in words):
        return "send"
    if words and all(word in CLEAR_WORDS for word in words):
        return "clear"
    return None


def find_output(name):
    for index, device in enumerate(sd.query_devices()):
        if name in device["name"] and device["max_output_channels"] > 0:
            return index
    return None


# Voices that are jokes or very robotic: not offered for a meeting.
NOVELTY_VOICES = {
    "Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Fred", "Good News",
    "Jester", "Junior", "Kathy", "Organ", "Ralph", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox",
}
# macOS does not report gender through `say`; these are its well-known English voices.
GENDER = {
    "Samantha": "female", "Karen": "female", "Moira": "female", "Tessa": "female", "Tara": "female",
    "Flo": "female", "Grandma": "female", "Sandy": "female", "Shelley": "female",
    "Ava": "female", "Allison": "female", "Susan": "female", "Zoe": "female", "Serena": "female",
    "Stephanie": "female", "Kate": "female", "Fiona": "female", "Nicky": "female",
    "Daniel": "male", "Rishi": "male", "Aman": "male", "Eddy": "male", "Grandpa": "male", "Reed": "male",
    "Rocko": "male", "Tom": "male", "Alex": "male", "Evan": "male", "Nathan": "male", "Oliver": "male",
    "Lee": "male", "Gordon": "male", "Arthur": "male",
}


def list_voices():
    """English voices installed on this Mac, best first, as dicts: id (what `say -v` takes),
    name, language, gender ("female"/"male"/None), quality ("premium"/"enhanced"/"standard").

    More and better voices: System Settings > Accessibility > Spoken Content > System voice >
    Manage Voices.
    """
    listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    voices = []
    for voice_id, language in re.findall(r"^(.+?)\s{2,}(en_\w+)", listing, flags=re.M):
        voice_id = voice_id.strip()
        base = voice_id.split(" (")[0]
        if base in NOVELTY_VOICES:
            continue
        quality = "premium" if "(Premium)" in voice_id else "enhanced" if "(Enhanced)" in voice_id else "standard"
        voices.append({
            "id": voice_id, "name": base, "language": language.replace("_", "-"),
            "gender": GENDER.get(base), "quality": quality,
        })
    rank = {"premium": 0, "enhanced": 1, "standard": 2}
    return sorted(voices, key=lambda v: (rank[v["quality"]], v["name"]))


def saved_voice():
    return prefs.load().get("voice")


def save_voice(voice_id):
    prefs.save(voice=voice_id)


def pick_voice(voices):
    """The saved choice if still installed, else the best installed voice (Premium, Enhanced,
    then Samantha)."""
    ids = [v["id"] for v in voices]
    if saved_voice() in ids:
        return saved_voice()
    if voices and voices[0]["quality"] != "standard":
        return voices[0]["id"]
    return "Samantha" if "Samantha" in ids else (ids[0] if ids else None)


def synthesize(text, voice):
    """English speech for `text` as float32 mono at RATE."""
    with tempfile.TemporaryDirectory() as folder:
        script = os.path.join(folder, "text.txt")  # a file, so text starting with "-" is not an option
        audio = os.path.join(folder, "speech.wav")
        with open(script, "w") as f:
            f.write(text)
        command = ["say", "-f", script, "--file-format=WAVE", f"--data-format=LEI16@{RATE}", "-o", audio]
        if voice:
            command[1:1] = ["-v", voice]
        subprocess.run(command, check=True)
        with wave.open(audio) as w:
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return samples.astype(np.float32) / 32768


class VoiceOut:
    """Owns the virtual mic: passes the real mic through, or plays confirmed English speech.

    Also keeps the draft: translations of Jun's Korean lines while in interpret mode.
    """

    def __init__(self, mic_index, emit):
        self.emit = emit
        self.device = find_output(VOICE_DEVICE)
        self.available = self.device is not None
        self.mode = "direct"
        self.voices = list_voices()
        self.voice = pick_voice(self.voices)
        self.lock = threading.Lock()
        self.playing = None  # float32 speech being played
        self.position = 0
        self.korean_mic_lines = set()  # ids of Jun's Korean lines since the draft was cleared
        self.parts = {}  # line id -> English translation, for the draft
        self.last_line_time = 0.0  # when the draft's latest Korean line was said
        self.rendered = (None, None)  # (text, audio) rendered ahead of Enter
        # Monitor: Jun also hears what the meeting hears, quietly, on his real output device.
        saved = prefs.load()
        self.monitor = saved.get("monitor", True) is not False
        try:
            self.monitor_volume = min(1.0, max(0.0, float(saved.get("monitor_volume", 0.5))))
        except (TypeError, ValueError):
            self.monitor_volume = 0.5
        self.real_output = lambda: None  # name of the real output device; set by the transcriber
        self.stream = None
        if self.available:
            self.stream = sd.Stream(
                device=(mic_index, self.device),
                samplerate=RATE,
                channels=(1, 2),
                dtype="float32",
                callback=self._callback,
            )

    # ---- audio

    def _callback(self, indata, outdata, frames, time_info, status):
        speech = np.zeros(frames, dtype=np.float32)
        with self.lock:
            if self.playing is not None:
                chunk = self.playing[self.position : self.position + frames]
                speech[: len(chunk)] = chunk
                self.position += frames
                if self.position >= len(self.playing):
                    self.playing = None
            speaking = self.playing is not None or speech.any()
        mic = indata[:, 0] if self.mode == "direct" and not speaking else 0.0
        outdata[:] = (mic + speech)[:, None]

    def start(self):
        if self.stream:
            self.stream.start()
        self.emit(self.as_event())

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()

    # ---- state

    def as_event(self):
        return {
            "type": "voice",
            "available": self.available,
            "mode": self.mode,
            "device": VOICE_DEVICE,
            "voice": self.voice,
            "voices": self.voices,
            "monitor": self.monitor,
            "monitor_volume": self.monitor_volume,
        }

    def set_voice(self, voice_id):
        if voice_id in [v["id"] for v in self.voices]:
            self.voice = voice_id
            save_voice(voice_id)
            self.rendered = (None, None)  # a draft rendered ahead used the old voice
            self.emit(self.as_event())
            if self.parts:
                self._draft_changed()

    def preview(self, voice_id=None):
        """Say a short sample in the chosen voice, only in Jun's headphones: never into the meeting."""
        voice_id = voice_id or self.voice

        def work():
            audio = synthesize("Hello, this is how I will sound in the meeting.", voice_id)
            self._play_monitor(audio, force=True)

        threading.Thread(target=work, daemon=True).start()

    def set_mode(self, mode):
        if mode in ("direct", "interpret") and self.available:
            self.mode = mode
            self.discard()
            self.emit(self.as_event())

    def set_monitor(self, on=None, volume=None):
        if on is not None:
            self.monitor = bool(on)
        if volume is not None:
            self.monitor_volume = min(1.0, max(0.0, float(volume)))
        prefs.save(monitor=self.monitor, monitor_volume=self.monitor_volume)
        self.emit(self.as_event())

    def _play_monitor(self, audio, force=False):
        """Play `audio` on the real output device, in a separate process (see monitor_play.py).
        `force` plays even with the monitor switched off (a voice preview), at least quietly."""
        device = self.real_output()
        volume = max(self.monitor_volume, 0.4) if force else self.monitor_volume
        if not device or volume <= 0 or not (self.monitor or force):
            return
        handle, path = tempfile.mkstemp(suffix=".wav")
        os.close(handle)
        scaled = np.clip(audio * volume, -1, 1)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes((scaled * 32767).astype(np.int16).tobytes())
        subprocess.Popen([sys.executable, MONITOR_PLAYER, device, path])

    def draft(self):
        return " ".join(self.parts[i] for i in sorted(self.parts))

    def _draft_changed(self):
        text = self.draft()
        self.emit({"type": "draft", "text": text})
        if text and self.mode == "interpret" and self.available:  # only the Avatar voice needs audio
            threading.Thread(target=self._render_ahead, args=(text,), daemon=True).start()

    def _render_ahead(self, text):
        audio = synthesize(text, self.voice)
        if text == self.draft():
            self.rendered = (text, audio)

    def observe(self, event):
        """Watch the event stream for Jun's Korean lines, their translations and spoken commands.

        The draft is built in every mode: Jun speaks Korean, reads the English that appears, and
        says it himself. Only with the Avatar voice on does "오케이" send it by computer voice.
        """
        if event["type"] == "line" and event["source"] == "MIC":
            command = command_of(event["text"])
            if command == "send":
                if self.mode == "interpret":
                    self._send_when_translated()
            elif command == "clear":
                self.discard()
            elif event["lang"] == "ko":
                if self.korean_mic_lines and time.time() - self.last_line_time > NEW_DRAFT_AFTER_SECONDS:
                    self.discard()  # Jun said it again: the new version replaces the draft
                self.korean_mic_lines.add(event["id"])
                self.last_line_time = time.time()
        elif event["type"] == "translation" and event["id"] in self.korean_mic_lines:
            if not event["text"].startswith("(translation failed"):
                self.parts[event["id"]] = event["text"]
                self._draft_changed()

    def _send_when_translated(self):
        """Speak the draft once every line in it has its translation (or after a short wait)."""

        def work():
            deadline = time.time() + WAIT_FOR_TRANSLATION_SECONDS
            while time.time() < deadline and not self.korean_mic_lines <= set(self.parts):
                time.sleep(0.1)
            self.speak(self.draft())

        threading.Thread(target=work, daemon=True).start()

    def speak(self, text):
        """Speak `text` (the draft, possibly edited on the page) and clear the draft."""
        text = text.strip()
        self.discard()
        if not text or not self.available:
            return
        if re.search(r"[가-힣]", text):
            # An English voice makes no sound for Korean; do not send silence into the meeting.
            self.emit({"type": "info", "text": "not spoken: the text is Korean (translate it first)"})
            return

        def work():
            cached_text, cached_audio = self.rendered
            audio = cached_audio if cached_text == text else synthesize(text, self.voice)
            if not len(audio):
                self.emit({"type": "info", "text": "not spoken: the voice produced no sound"})
                return
            self._play_monitor(audio)  # starts first: the helper process needs a moment to load
            with self.lock:
                self.playing = audio
                self.position = 0
            seconds = round(len(audio) / RATE, 1)
            self.emit({"type": "spoken", "text": text, "seconds": seconds, "time": time.strftime("%H:%M:%S")})

        threading.Thread(target=work, daemon=True).start()

    def discard(self):
        self.korean_mic_lines.clear()
        self.last_line_time = 0.0
        had_draft = bool(self.parts)
        self.parts.clear()
        self.rendered = (None, None)
        if had_draft:
            self.emit({"type": "draft", "text": ""})
