"""Step 1: check that system audio (BlackHole 2ch) and the microphone both show signal.

Run with the venv active:
    python audio_test.py

While it runs, the output is routed through BlackHole (audio_output.Route) and restored on exit.
Play a video or join a call, then speak. Both bars should move. Press Ctrl+C to stop.
"""

import sys

import numpy as np
import sounddevice as sd

import audio_output

SYSTEM_NAME = "BlackHole 2ch"
MIC_NAME = "MacBook Air Microphone"
BAR_WIDTH = 40


def find_input(name):
    """Return the device index for a named input, or None."""
    for index, device in enumerate(sd.query_devices()):
        if name in device["name"] and device["max_input_channels"] > 0:
            return index
    return None


def find_mic():
    """MIC_NAME if present, else the default input. Never BlackHole, which is the system audio.

    Do not rely on the macOS default input alone: it can end up set to BlackHole 2ch,
    and then the "mic" stream is a copy of the system audio.
    """
    index = find_input(MIC_NAME)
    if index is not None:
        return index
    default = sd.default.device[0]
    if default >= 0 and SYSTEM_NAME not in sd.query_devices(default)["name"]:
        return default
    return None


def list_inputs():
    print("Input devices:")
    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0:
            print(f"  [{index}] {device['name']} ({device['max_input_channels']} ch)")
    print()


def level_bar(rms):
    # Map RMS (0..1) to a bar on a rough dB scale so quiet speech is still visible.
    db = 20 * np.log10(max(rms, 1e-6))
    fraction = min(max((db + 60) / 60, 0.0), 1.0)
    return "#" * int(fraction * BAR_WIDTH)


def open_stream(device_index, label, levels):
    channels = min(sd.query_devices(device_index)["max_input_channels"], 2)

    def callback(indata, frames, time_info, status):
        levels[label] = float(np.sqrt(np.mean(np.square(indata))))

    return sd.InputStream(
        device=device_index,
        channels=channels,
        samplerate=None,
        callback=callback,
    )


def main():
    list_inputs()

    system_index = find_input(SYSTEM_NAME)
    mic_index = find_mic()

    if system_index is None:
        print(f"Could not find an input named '{SYSTEM_NAME}'. Check the device list above.")
        sys.exit(1)
    if mic_index is None:
        print(f"Could not find '{MIC_NAME}' or another non-BlackHole input. Check the list above.")
        sys.exit(1)

    print(f"System audio: [{system_index}] {sd.query_devices(system_index)['name']}")
    print(f"Microphone:   [{mic_index}] {sd.query_devices(mic_index)['name']}")
    print("Ctrl+C to stop.\n")

    levels = {"system": 0.0, "mic": 0.0}

    route = audio_output.Route()
    with open_stream(system_index, "system", levels), open_stream(mic_index, "mic", levels):
        try:
            while True:
                sd.sleep(200)
                print(
                    f"\rSYSTEM |{level_bar(levels['system']):<{BAR_WIDTH}}|"
                    f"  MIC |{level_bar(levels['mic']):<{BAR_WIDTH}}|",
                    end="",
                    flush=True,
                )
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            route.stop()


if __name__ == "__main__":
    main()
