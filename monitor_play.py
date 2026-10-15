"""Play a WAV file on one output device, chosen by name, then delete the file.

voice_out.py runs this for the monitor (Jun hearing his own interpreted voice). It plays on the
real device (e.g. "External Headphones"), not on the default output: while secondchair runs the
default output also feeds BlackHole 2ch, and the voice would come back as a "Them" line.
A fresh process is used because it sees devices plugged in after secondchair started.

Usage: python monitor_play.py "<device name>" <file.wav>
"""

import os
import sys
import wave

import numpy as np
import sounddevice as sd


def main():
    name, path = sys.argv[1], sys.argv[2]
    try:
        with wave.open(path) as w:
            rate = w.getframerate()
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        devices = sd.query_devices()
        index = next(
            (i for i, d in enumerate(devices) if d["name"] == name and d["max_output_channels"] > 0),
            None,
        )
        if index is None:
            return  # the device went away (headphones unplugged): nothing to do
        sd.play(samples.astype(np.float32) / 32768, rate, device=index)
        sd.wait()
    finally:
        os.remove(path)


if __name__ == "__main__":
    main()
