"""Route the system output through BlackHole 2ch only while secondchair runs.

Runs the native helper `native/route` (built from native/route.swift on first use). The helper
makes a temporary multi-output device (the user's real output + BlackHole), makes it the
default output, follows device changes, and restores the real output when it stops.
The user's audio settings are not changed outside secondchair.
"""

import os
import subprocess
import threading

from events import print_event

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "native", "route.swift")
HELPER = os.path.join(HERE, "native", "route")


def build_if_needed():
    if os.path.exists(HELPER) and os.path.getmtime(HELPER) >= os.path.getmtime(SOURCE):
        return
    print("[building native/route ...]", flush=True)
    subprocess.run(["swiftc", "-O", SOURCE, "-o", HELPER], check=True)


class Route:
    """The running helper. `kind` is "headphones" or "speakers" for the current real device."""

    def __init__(self, emit=print_event):
        build_if_needed()
        self.emit = emit
        self.kind = None
        self.device = None
        self.ready = threading.Event()
        self.process = subprocess.Popen([HELPER], stdout=subprocess.PIPE, text=True)
        threading.Thread(target=self._read, daemon=True).start()
        if not self.ready.wait(5):
            self.stop()
            raise SystemExit("native/route did not start (see the message above).")

    def _read(self):
        for line in self.process.stdout:
            word, _, rest = line.strip().partition(" ")
            if word == "route":
                # The transcriber's main loop reports the new device and kind as a status event.
                self.kind, _, self.device = rest.partition(" ")
                self.ready.set()
            elif word == "restored":
                self.emit({"type": "info", "text": f"output restored to {rest}"})

    def on_speakers(self):
        return self.kind == "speakers"

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
