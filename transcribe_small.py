"""Transcription with whisper-small (fast, less accurate).

Run: python transcribe_small.py   (options and output switching: see transcribe_stream.py)
"""

from transcribe_stream import main

MODEL = "mlx-community/whisper-small-mlx"

if __name__ == "__main__":
    main(MODEL)
